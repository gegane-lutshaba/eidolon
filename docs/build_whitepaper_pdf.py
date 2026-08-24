#!/usr/bin/env python
"""Render docs/whitepaper.md to a print-quality PDF (docs/whitepaper.pdf).

Markdown -> styled HTML -> PDF via Playwright's bundled Chromium, so tables,
code, and the embedded diagrams render faithfully (no LaTeX table overflow).

    uv sync  # then:
    uv pip install playwright markdown pygments
    uv run playwright install chromium
    uv run python docs/build_whitepaper_pdf.py
"""

from __future__ import annotations

import pathlib

import markdown

DOCS = pathlib.Path(__file__).resolve().parent
SRC = DOCS / "whitepaper.md"
HTML = DOCS / "_whitepaper_build.html"
PDF = DOCS / "whitepaper.pdf"

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm; }
* { box-sizing: border-box; }
body { font: 10.7pt/1.55 "Helvetica Neue", Arial, sans-serif; color: #1c2230;
       max-width: 100%; margin: 0; }
h1 { font-size: 25pt; line-height: 1.15; margin: 0 0 4pt; letter-spacing: -.2pt; }
h1 + p strong { color: #0f1320; }
h2 { font-size: 15pt; margin: 20pt 0 6pt; padding-top: 4pt;
     border-top: 1px solid #e6e8ee; break-after: avoid; }
h3 { font-size: 12pt; margin: 14pt 0 4pt; color: #2b3350; break-after: avoid; }
p, li { orphans: 3; widows: 3; }
a { color: #4b49c7; text-decoration: none; }
strong { color: #10152a; }
hr { border: none; border-top: 1px solid #e6e8ee; margin: 14pt 0; }
code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 9.3pt;
       background: #f3f4f8; padding: 1px 4px; border-radius: 4px; }
pre { background: #f6f7fb; border: 1px solid #e6e8ee; border-radius: 8px;
      padding: 10px 12px; overflow: auto; break-inside: avoid; }
pre code { background: none; padding: 0; font-size: 9pt; }
img { max-width: 100%; display: block; margin: 10pt auto; border: 1px solid #e6e8ee;
      border-radius: 8px; }
table { width: 100%; border-collapse: collapse; margin: 8pt 0; font-size: 8.9pt;
        break-inside: avoid; }
th, td { border: 1px solid #dfe2ea; padding: 4px 7px; text-align: left;
         vertical-align: top; }
th { background: #f3f4f8; font-weight: 700; }
blockquote { margin: 8pt 0; padding: 2pt 12pt; border-left: 3px solid #4b49c7;
             color: #3a4258; }
em { color: #3a4258; }
h1, .byline { break-after: avoid; }
"""


def main() -> int:
    body = markdown.markdown(
        SRC.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code", "codehilite", "sane_lists", "attr_list", "toc"],
        extension_configs={"codehilite": {"noclasses": True, "pygments_style": "friendly"}},
    )
    HTML.write_text(
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>{CSS}</style></head><body>{body}</body></html>",
        encoding="utf-8",
    )

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(HTML.as_uri(), wait_until="networkidle")
        page.pdf(
            path=str(PDF), format="A4", print_background=True,
            margin={"top": "18mm", "bottom": "20mm", "left": "16mm", "right": "16mm"},
            display_header_footer=True,
            header_template="<div></div>",
            footer_template=(
                "<div style='font-size:8px;color:#8a93a6;width:100%;padding:0 16mm;"
                "display:flex;justify-content:space-between;'>"
                "<span>EIDOLON — Provable Delegated Agency · Mthandazo Ndhlovu</span>"
                "<span class='pageNumber'></span></div>"
            ),
        )
        browser.close()
    HTML.unlink(missing_ok=True)
    print(f"wrote {PDF} ({PDF.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
