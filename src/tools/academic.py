"""Academic paper search for the scientific profile (CLAUDE.md §7): PubMed,
OpenAlex, and arXiv via their public APIs, exposed to the worker as in-process
MCP tools. Parsers are pure functions over raw payloads so they unit-test
against canned fixtures without network."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import Any

import httpx

from src.settings import RetryCfg, Settings
from src.tools import ConnectorError, http_get_with_retry

_PUBMED_ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_PUBMED_ESUMMARY = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
_OPENALEX_WORKS = "https://api.openalex.org/works"
_ARXIV_QUERY = "https://export.arxiv.org/api/query"
_ABSTRACT_CHARS = 500


# --- pure parsers (unit-tested against fixtures) ------------------------------


def parse_pubmed_esearch(payload: dict) -> list[str]:
    try:
        return list(payload["esearchresult"]["idlist"])
    except (KeyError, TypeError) as exc:
        raise ConnectorError(f"unexpected PubMed esearch payload: {exc}") from exc


def parse_pubmed_esummary(payload: dict) -> list[dict[str, Any]]:
    try:
        result = payload["result"]
        papers = []
        for pmid in result["uids"]:
            item = result[pmid]
            papers.append(
                {
                    "title": item.get("title", "(untitled)"),
                    "venue": item.get("fulljournalname") or item.get("source", ""),
                    "year": (item.get("pubdate") or "")[:4],
                    "authors": [a.get("name", "") for a in item.get("authors", [])][:6],
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    "extra": item.get("pubtype", []),
                }
            )
        return papers
    except (KeyError, TypeError) as exc:
        raise ConnectorError(f"unexpected PubMed esummary payload: {exc}") from exc


def reconstruct_openalex_abstract(inverted: dict[str, list[int]] | None) -> str:
    if not inverted:
        return ""
    positions: dict[int, str] = {}
    for word, indexes in inverted.items():
        for index in indexes:
            positions[index] = word
    return " ".join(positions[i] for i in sorted(positions))


def parse_openalex_works(payload: dict) -> list[dict[str, Any]]:
    try:
        papers = []
        for work in payload.get("results", []):
            location = work.get("primary_location") or {}
            source = location.get("source") or {}
            papers.append(
                {
                    "title": work.get("title") or "(untitled)",
                    "venue": source.get("display_name", ""),
                    "year": work.get("publication_year", ""),
                    "authors": [
                        (a.get("author") or {}).get("display_name", "")
                        for a in work.get("authorships", [])
                    ][:6],
                    "url": location.get("landing_page_url")
                    or work.get("doi")
                    or work.get("id", ""),
                    "cited_by": work.get("cited_by_count", 0),
                    "abstract": reconstruct_openalex_abstract(
                        work.get("abstract_inverted_index")
                    )[:_ABSTRACT_CHARS],
                    # Journal-reputation enrichment (roadmap): OpenAlex carries both
                    # signals directly on the work payload — no extra API call.
                    # is_retracted is unambiguous/machine-checkable. is_in_doaj is
                    # None when OpenAlex has no source record at all (unknown, not
                    # a negative signal) vs. an explicit True/False when it does.
                    "is_retracted": bool(work.get("is_retracted")),
                    "is_in_doaj": source.get("is_in_doaj") if source else None,
                }
            )
        return papers
    except (AttributeError, TypeError) as exc:
        raise ConnectorError(f"unexpected OpenAlex payload: {exc}") from exc


_ATOM = "{http://www.w3.org/2005/Atom}"


def parse_arxiv_atom(xml_text: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ConnectorError(f"unexpected arXiv payload: {exc}") from exc
    papers = []
    for entry in root.findall(f"{_ATOM}entry"):
        papers.append(
            {
                "title": " ".join((entry.findtext(f"{_ATOM}title") or "").split()),
                "venue": "arXiv",
                "year": (entry.findtext(f"{_ATOM}published") or "")[:4],
                "authors": [
                    a.findtext(f"{_ATOM}name") or ""
                    for a in entry.findall(f"{_ATOM}author")
                ][:6],
                "url": entry.findtext(f"{_ATOM}id") or "",
                "abstract": " ".join(
                    (entry.findtext(f"{_ATOM}summary") or "").split()
                )[:_ABSTRACT_CHARS],
            }
        )
    return papers


def reputation_flag(paper: dict[str, Any]) -> str:
    """Journal-reputation enrichment (roadmap): retraction is an unambiguous,
    machine-checkable correctness signal worth surfacing loudly, BEFORE the
    worker decides whether to read/cite the paper — CLAUDE.md's scientific
    rubric demands current, non-superseded evidence. DOAJ non-membership is a
    softer legitimacy signal (DOAJ vets editorial/peer-review standards, so a
    predatory venue is essentially never a member) — phrased as something to
    verify, not a verdict, since plenty of legitimate paywalled/non-OA venues
    are also non-members. Only fires on an EXPLICIT False (real OpenAlex source
    metadata saying "not DOAJ"), never on missing/unknown source metadata."""
    if paper.get("is_retracted"):
        return "RETRACTED"
    if paper.get("is_in_doaj") is False:
        return "non-DOAJ venue, verify legitimacy"
    return ""


def format_papers(papers: list[dict[str, Any]], source_name: str) -> str:
    if not papers:
        return f"{source_name}: no results."
    lines = [f"{source_name}: {len(papers)} results"]
    for i, p in enumerate(papers, 1):
        authors = ", ".join(a for a in p.get("authors", []) if a)
        extra = []
        if p.get("cited_by"):
            extra.append(f"cited_by={p['cited_by']}")
        if p.get("extra"):
            extra.append(f"type={','.join(p['extra'][:3])}")
        flag = reputation_flag(p)
        if flag:
            extra.append(f"⚠ {flag}")
        lines.append(
            f"{i}. {p['title']} ({p.get('venue','')}, {p.get('year','')}) — {authors}"
            + (f" [{'; '.join(extra)}]" if extra else "")
            + f"\n   URL: {p['url']}"
            + (f"\n   Abstract: {p['abstract']}" if p.get("abstract") else "")
        )
    return "\n".join(lines)


# --- fetchers ------------------------------------------------------------------


async def _get_json(url: str, params: dict, timeout: float, retry_cfg: RetryCfg) -> dict:
    try:
        response = await http_get_with_retry(
            url, retry_cfg=retry_cfg, timeout=timeout, params=params
        )
    except httpx.HTTPError as exc:
        raise ConnectorError(f"academic API call failed ({url}): {exc}") from exc
    try:
        return response.json()
    except Exception as exc:  # noqa: BLE001 — JSONDecodeError + a bogus
        # Content-Encoding/charset (AssertionError/LookupError from httpx's decoder)
        # both mean an unusable body; surface as a connector failure, not a crash.
        raise ConnectorError(f"academic API returned an undecodable body ({url}): {exc!r}") from exc


async def search_pubmed(
    query: str, max_results: int, timeout: float, retry_cfg: RetryCfg
) -> str:
    ids = parse_pubmed_esearch(
        await _get_json(
            _PUBMED_ESEARCH,
            {"db": "pubmed", "term": query, "retmax": max_results, "retmode": "json",
             "sort": "relevance"},
            timeout,
            retry_cfg,
        )
    )
    if not ids:
        return "PubMed: no results."
    papers = parse_pubmed_esummary(
        await _get_json(
            _PUBMED_ESUMMARY,
            {"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            timeout,
            retry_cfg,
        )
    )
    return format_papers(papers, "PubMed")


async def search_openalex(
    query: str, max_results: int, timeout: float, retry_cfg: RetryCfg
) -> str:
    payload = await _get_json(
        _OPENALEX_WORKS, {"search": query, "per-page": max_results}, timeout, retry_cfg
    )
    return format_papers(parse_openalex_works(payload), "OpenAlex")


async def search_arxiv(
    query: str, max_results: int, timeout: float, retry_cfg: RetryCfg
) -> str:
    try:
        response = await http_get_with_retry(
            _ARXIV_QUERY,
            retry_cfg=retry_cfg,
            timeout=timeout,
            params={"search_query": f"all:{query}", "max_results": max_results},
        )
    except httpx.HTTPError as exc:
        raise ConnectorError(f"academic API call failed (arXiv): {exc}") from exc
    try:
        body = response.text
    except Exception as exc:  # noqa: BLE001 — bogus Content-Encoding/charset
        raise ConnectorError(f"arXiv returned an undecodable body: {exc!r}") from exc
    return format_papers(parse_arxiv_atom(body), "arXiv")


def _normalize_papers(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _snippet(p: dict[str, Any]) -> str:
        abstract = (p.get("abstract") or "")[:400]
        # Journal-reputation enrichment (roadmap): the flag rides into the
        # pipeline-mode snippet (which becomes reader.read_source's `why`) since
        # that's the only channel carrying paper metadata past URL selection —
        # prepended (not truncated away) so it survives the 400-char abstract cap.
        flag = reputation_flag(p)
        return f"[⚠ {flag}] {abstract}" if flag else abstract

    return [
        {
            "title": p.get("title", "(untitled)"),
            "url": p.get("url", ""),
            "snippet": _snippet(p),
        }
        for p in papers
        if p.get("url")
    ]


async def pubmed_results(
    query: str, max_results: int, timeout: float, retry_cfg: RetryCfg
) -> list[dict[str, Any]]:
    """Normalized raw results for pipeline-mode URL selection."""
    ids = parse_pubmed_esearch(
        await _get_json(
            _PUBMED_ESEARCH,
            {"db": "pubmed", "term": query, "retmax": max_results, "retmode": "json",
             "sort": "relevance"},
            timeout,
            retry_cfg,
        )
    )
    if not ids:
        return []
    papers = parse_pubmed_esummary(
        await _get_json(
            _PUBMED_ESUMMARY,
            {"db": "pubmed", "id": ",".join(ids), "retmode": "json"},
            timeout,
            retry_cfg,
        )
    )
    return _normalize_papers(papers)


async def openalex_results(
    query: str, max_results: int, timeout: float, retry_cfg: RetryCfg
) -> list[dict[str, Any]]:
    """Normalized raw results for pipeline-mode URL selection."""
    payload = await _get_json(
        _OPENALEX_WORKS, {"search": query, "per-page": max_results}, timeout, retry_cfg
    )
    return _normalize_papers(parse_openalex_works(payload))


def build_academic_mcp(settings: Settings):
    """In-process MCP server with the three paper-search tools."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    timeout = settings.reader.fetch_timeout_seconds
    max_results = settings.search.max_results

    retry_cfg = settings.retry

    def _wrap(coro_fn, label):
        async def handler(args: dict) -> dict:
            query = str(args.get("query", "")).strip()
            if not query:
                return {"content": [{"type": "text", "text": f"{label}: empty query"}],
                        "is_error": True}
            try:
                text = await coro_fn(query, max_results, timeout, retry_cfg)
            except ConnectorError as exc:
                return {"content": [{"type": "text", "text": f"SEARCH FAILED: {exc}"}],
                        "is_error": True}
            return {"content": [{"type": "text", "text": text}]}

        return handler

    pubmed = tool(
        "search_pubmed",
        "Search PubMed for peer-reviewed biomedical literature (RCTs, "
        "meta-analyses, clinical studies). Returns titles, venues, years, "
        "authors, and PubMed URLs to feed into read_source.",
        {"query": str},
    )(_wrap(search_pubmed, "PubMed"))
    openalex = tool(
        "search_openalex",
        "Search OpenAlex across all scholarly literature. Returns titles, "
        "venues, years, citation counts, abstracts, and landing-page URLs to "
        "feed into read_source.",
        {"query": str},
    )(_wrap(search_openalex, "OpenAlex"))
    arxiv = tool(
        "search_arxiv",
        "Search arXiv preprints. Returns titles, years, authors, abstracts, "
        "and arXiv URLs to feed into read_source.",
        {"query": str},
    )(_wrap(search_arxiv, "arXiv"))

    return create_sdk_mcp_server("academic", tools=[pubmed, openalex, arxiv])
