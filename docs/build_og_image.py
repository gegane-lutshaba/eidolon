#!/usr/bin/env python
"""Render EIDOLON's arcade brand cards to PNG (link previews + GitHub social).

    uv sync --extra docs && uv run playwright install chromium
    uv run --extra docs python docs/build_og_image.py

Outputs:
  docs/brand/og.png             1200x630  (Open Graph / X / link previews)
  docs/brand/github-social.png  1280x640  (GitHub → Settings → Social preview)
  src/eidolon/api/static/og.png (copy served at /og.png)
"""

from __future__ import annotations

import pathlib
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRAND = ROOT / "docs" / "brand"
STATIC = ROOT / "src" / "eidolon" / "api" / "static"

CARD = """<!doctype html><html><head><meta charset="utf-8"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&display=swap" rel="stylesheet"/>
<style>
  :root {{ --bg:#07090f; --ink:#d7e0ea; --dim:#8592a6; --green:#39d98a; --amber:#f2b84b;
    --red:#ff5c5c; --cyan:#4fc7ff; --accent:#8b7bff; --pixel:"Press Start 2P",monospace; }}
  * {{ box-sizing:border-box; margin:0; }}
  html,body {{ width:{w}px; height:{h}px; }}
  body {{ background:radial-gradient(ellipse at 50% 38%, #10162a 0%, #07090f 70%);
    color:var(--ink); font-family:ui-monospace,Menlo,monospace; position:relative;
    overflow:hidden; display:flex; flex-direction:column; align-items:center;
    justify-content:center; padding:0 60px; }}
  body::before {{ content:""; position:absolute; inset:0;
    background:repeating-linear-gradient(0deg, rgba(0,0,0,.20) 0 1px, transparent 1px 3px); }}
  /* perspective grid floor */
  body::after {{ content:""; position:absolute; left:-40%; right:-40%; bottom:-14%; height:52%;
    background:repeating-linear-gradient(90deg, rgba(139,123,255,.28) 0 2px, transparent 2px 90px),
      repeating-linear-gradient(0deg, rgba(139,123,255,.22) 0 2px, transparent 2px 46px);
    transform:perspective(500px) rotateX(64deg); mask-image:linear-gradient(transparent, #000 55%); }}
  .z {{ position:relative; z-index:2; text-align:center; }}
  .marq {{ font-family:var(--pixel); font-size:15px; color:var(--amber); letter-spacing:3px; }}
  .logo {{ font-family:var(--pixel); font-size:{logo}px; color:var(--accent); margin:22px 0 8px;
    letter-spacing:3px; text-shadow:0 0 26px rgba(139,123,255,.7); }}
  .tag {{ font-family:var(--pixel); font-size:{tag}px; line-height:1.7; }}
  .tag .g {{ color:var(--green); }} .tag .c {{ color:var(--cyan); }} .tag .r {{ color:var(--red); }}
  .feed {{ display:flex; gap:12px; justify-content:center; margin:30px 0 22px; flex-wrap:wrap; }}
  .chip {{ font-family:var(--pixel); font-size:12px; padding:10px 14px; border-radius:6px;
    border:1px solid rgba(255,255,255,.08); }}
  .ok {{ background:rgba(57,217,138,.14); color:var(--green); }}
  .hold {{ background:rgba(242,184,75,.14); color:var(--amber); }}
  .deny {{ background:rgba(255,92,92,.18); color:var(--red); }}
  .sub {{ color:var(--dim); font-size:20px; margin-top:6px; }}
  .url {{ font-family:var(--pixel); font-size:16px; color:var(--cyan); margin-top:20px; }}
</style></head><body>
  <div class="z">
    <div class="marq">★ ONYX ARCADE ★</div>
    <div class="logo">E I D O L O N</div>
    <div class="tag">YOUR AGENT. <span class="g">SEEN.</span> <span class="c">BOUNDED.</span> <span class="r">REVOCABLE.</span></div>
    <div class="feed">
      <span class="chip ok">✓ ACT · read_file</span>
      <span class="chip hold">⚑ HELD · send_email</span>
      <span class="chip deny">⛔ DENY · wire_funds</span>
    </div>
    <div class="sub">the cryptographic authority layer for AI agents</div>
    <div class="url">eidolon.onyxcreator.com</div>
  </div>
</body></html>"""


def render(path: pathlib.Path, w: int, h: int) -> None:
    from playwright.sync_api import sync_playwright

    logo = int(w * 0.058)
    tag = int(w * 0.022)
    html = CARD.format(w=w, h=h, logo=logo, tag=tag)
    tmp = BRAND / "_card.html"
    tmp.write_text(html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        pg.goto(tmp.as_uri(), wait_until="networkidle")
        pg.wait_for_timeout(400)  # let the webfont paint
        pg.screenshot(path=str(path), clip={"x": 0, "y": 0, "width": w, "height": h})
        b.close()
    tmp.unlink(missing_ok=True)
    print(f"wrote {path}  ({path.stat().st_size // 1024} KB)")


def main() -> int:
    BRAND.mkdir(parents=True, exist_ok=True)
    render(BRAND / "og.png", 1200, 630)
    render(BRAND / "github-social.png", 1280, 640)
    shutil.copy2(BRAND / "og.png", STATIC / "og.png")
    print(f"copied og.png -> {STATIC / 'og.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
