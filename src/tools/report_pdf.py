"""Markdown -> PDF for the final report (CLAUDE.md §6 deliverable).

Pure-Python (markdown + xhtml2pdf/reportlab) so it installs with `pip` on any OS
— no GTK/Pango/Cairo system libraries. That portability is why WeasyPrint was
rejected: it renders prettier but cannot "clone + run anywhere" on Windows.

PDF generation must NEVER crash a finished run (invariant: a report already exists
as REPORT.md). Every failure path returns ``(False, reason)`` and the caller keeps
the markdown; the PDF is a convenience artifact, not the source of truth.
"""

from __future__ import annotations

from pathlib import Path

# A light print stylesheet. xhtml2pdf supports a CSS subset — keep it simple so it
# renders identically everywhere. Tables get borders (the reports lean on them);
# headings, code, blockquotes and links get readable defaults.
_CSS = """
@page { size: A4; margin: 2cm; }
body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.4;
       color: #1a1a1a; }
h1 { font-size: 19pt; margin: 18px 0 8px; }
h2 { font-size: 15pt; margin: 16px 0 6px; }
h3 { font-size: 12.5pt; margin: 12px 0 4px; }
code, pre { font-family: Courier, monospace; background-color: #f4f4f4; font-size: 9pt; }
pre { padding: 6px; }
table { border-collapse: collapse; width: 100%; margin: 8px 0; }
th, td { border: 1px solid #999999; padding: 4px 6px; text-align: left; }
th { background-color: #eeeeee; }
blockquote { color: #555555; border-left: 3px solid #cccccc; padding-left: 10px; margin-left: 0; }
a { color: #1a5fb4; text-decoration: none; }
"""


def render_markdown_pdf(md_text: str, pdf_path: Path) -> tuple[bool, str]:
    """Render ``md_text`` to ``pdf_path``. Returns ``(ok, detail)`` and never raises.

    A missing optional dependency or a render error degrades to ``(False, reason)``
    so the run still finishes with REPORT.md intact.
    """
    try:
        import markdown as _markdown
        from xhtml2pdf import pisa
    except ImportError as exc:
        return False, f"PDF deps not installed ({exc}); pip install markdown xhtml2pdf"

    try:
        html_body = _markdown.markdown(
            md_text, extensions=["tables", "fenced_code", "sane_lists"]
        )
        html = (
            f"<html><head><meta charset='utf-8'><style>{_CSS}</style></head>"
            f"<body>{html_body}</body></html>"
        )
        with open(pdf_path, "wb") as fh:
            result = pisa.CreatePDF(src=html, dest=fh, encoding="utf-8")
        if result.err:
            return False, f"xhtml2pdf reported {result.err} error(s)"
        return True, f"wrote {pdf_path.name}"
    except Exception as exc:  # noqa: BLE001 — PDF must never crash a finished run
        return False, f"PDF render failed: {exc}"
