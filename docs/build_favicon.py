#!/usr/bin/env python
"""Rasterize the EIDOLON favicon to PNGs (PWA icon + apple-touch + .ico).

    uv run --extra docs python docs/build_favicon.py

Renders src/eidolon/api/static/favicon.svg on a dark rounded card at several
sizes via Playwright's Chromium.
"""

from __future__ import annotations

import pathlib

STATIC = pathlib.Path(__file__).resolve().parents[1] / "src" / "eidolon" / "api" / "static"
SVG = STATIC / "favicon.svg"


def render(out: pathlib.Path, size: int) -> None:
    from playwright.sync_api import sync_playwright

    svg = SVG.read_text(encoding="utf-8")
    html = (
        f"<!doctype html><html><head><meta charset='utf-8'>"
        f"<style>*{{margin:0}}html,body{{width:{size}px;height:{size}px;background:transparent}}"
        f"svg{{width:{size}px;height:{size}px}}</style></head><body>{svg}</body></html>"
    )
    tmp = STATIC / "_icon.html"
    tmp.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": size, "height": size}, device_scale_factor=1)
        pg.goto(tmp.as_uri(), wait_until="networkidle")
        pg.screenshot(path=str(out), omit_background=True,
                      clip={"x": 0, "y": 0, "width": size, "height": size})
        b.close()
    tmp.unlink(missing_ok=True)
    print(f"wrote {out.name} ({size}px)")


def main() -> int:
    render(STATIC / "icon-512.png", 512)          # PWA / manifest
    render(STATIC / "apple-touch-icon.png", 180)  # iOS home screen
    render(STATIC / "favicon-32.png", 32)         # served as /favicon.ico
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
