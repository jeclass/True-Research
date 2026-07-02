"""Malformed fixtures must be rejected loudly (StateError), valid ones must
round-trip byte-stable enough to reload."""

import pytest

from src.errors import StateError
from src.state import (
    FindingMeta,
    LedgerEntry,
    OpenQuestion,
    QuestionList,
    SourceRecord,
    SourceRegistry,
    Verdict,
    dump_finding,
    dump_questions,
    dump_sources,
    dump_verdict,
    parse_finding,
    parse_ledger,
    parse_questions,
    parse_sources,
    parse_verdict,
    utcnow,
)


def _question(**kw) -> OpenQuestion:
    base = dict(id="q-001", question="why?", priority=3, created_by="initializer")
    base.update(kw)
    return OpenQuestion(**base)


def test_questions_roundtrip():
    questions = QuestionList([_question(), _question(id="q-002", status="resolved")])
    reloaded = parse_questions(dump_questions(questions))
    assert reloaded == questions


def test_bad_status_rejected():
    text = dump_questions(QuestionList([_question()])).replace("open", "done")
    with pytest.raises(StateError, match="failed validation"):
        parse_questions(text)


def test_priority_out_of_range_rejected():
    with pytest.raises(StateError):
        parse_questions(
            "- id: q-001\n  question: why?\n  priority: 9\n  created_by: initializer\n"
        )


def test_unknown_field_rejected():
    with pytest.raises(StateError):
        parse_questions(
            "- id: q-001\n  question: why?\n  priority: 3\n"
            "  created_by: initializer\n  bogus: 1\n"
        )


def test_non_yaml_garbage_rejected():
    with pytest.raises(StateError):
        parse_questions("{[not yaml")


def test_sources_roundtrip_and_credibility_bounds():
    registry = SourceRegistry(
        {
            "src-1": SourceRecord(
                url="https://example.org",
                title="t",
                kind="web",
                credibility=100,
                retrieved_at=utcnow(),
            )
        }
    )
    assert parse_sources(dump_sources(registry)) == registry
    bad = dump_sources(registry).replace("100", "101")
    with pytest.raises(StateError):
        parse_sources(bad)


def test_ledger_rejects_negative_usd_and_unknown_session_type():
    with pytest.raises(StateError):
        parse_ledger(
            '[{"cycle": 0, "session_type": "worker", "model": "m", "endpoint": "e",'
            ' "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0,'
            ' "usd": -1, "wall_seconds": 0}]'
        )
    with pytest.raises(StateError):
        parse_ledger(
            '[{"cycle": 0, "session_type": "wizard", "model": "m", "endpoint": "e",'
            ' "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0,'
            ' "usd": 0, "wall_seconds": 0}]'
        )


def test_ledger_entry_requires_endpoint():
    with pytest.raises(StateError):
        parse_ledger(
            '[{"cycle": 0, "session_type": "worker", "model": "m", "endpoint": "",'
            ' "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0,'
            ' "usd": 0, "wall_seconds": 0}]'
        )
    entry = LedgerEntry(
        cycle=1,
        session_type="worker",
        model="claude-sonnet-4-6",
        endpoint="local",
        input_tokens=1,
        output_tokens=2,
        cached_tokens=3,
        usd=0.0,
        wall_seconds=0.5,
    )
    assert entry.endpoint == "local"


def test_finding_roundtrip_and_sourceless_rejected():
    meta = FindingMeta(question_id="q-001", source_ids=["src-1"], confidence=0.7)
    text = dump_finding(meta, "body text")
    parsed_meta, body = parse_finding(text, label="f")
    assert parsed_meta == meta and body.strip() == "body text"

    with pytest.raises(StateError):  # invariant 3: no sourceless findings
        parse_finding(
            "---\nquestion_id: q-001\nsource_ids: []\nconfidence: 0.5\n---\nbody",
            label="f",
        )


def test_finding_without_front_matter_rejected():
    with pytest.raises(StateError, match="front-matter"):
        parse_finding("just prose, no metadata", label="f")


def test_verdict_roundtrip():
    verdict = Verdict(
        passed=False,
        unmet_criteria=["a"],
        contradictions=["b"],
        new_questions=["c"],
        notes="needs work",
    )
    assert parse_verdict(dump_verdict(verdict), label="v") == verdict
