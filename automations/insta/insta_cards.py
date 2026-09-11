"""카드 제작 — 원고(JSON) + HTML 템플릿 → 1080×1350 JPEG 여러 장 (Playwright).

템플릿은 templates/<이름>.html (Jinja2). 색·글꼴 같은 겉모습은 프로필의 theme 값으로 넘긴다.
이 PC 에서는 설치된 Chrome 을, GitHub 서버에서는 Playwright 가 받은 Chromium 을 쓴다.
"""
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
FONT = HERE / "fonts" / "PretendardVariable.woff2"
WIDTH, HEIGHT = 1080, 1350

DEFAULT_THEME = {
    "bg": "#15171c", "fg": "#f5f6f8", "muted": "#9aa3b2", "accent": "#f2b544", "card": "#1f2229",
    "code_bg": "#0d0f13", "brand": "",
}


def build_slides(post: dict, handle: str) -> list[dict]:
    """원고 → 슬라이드 목록 (표지, 본문 n, 마무리)."""
    body = post.get("slides", [])
    total = len(body) + 2
    slides = [{"kind": "cover", "hook": post["hook"], "sub": post.get("sub", ""), "n": 1, "total": total, "handle": handle}]
    for i, s in enumerate(body, start=2):
        slides.append({"kind": "body", "title": s.get("title", ""), "body": s.get("body", ""),
                       "code": s.get("code", ""), "n": i, "total": total, "handle": handle, "idx": i - 1})
    slides.append({"kind": "cta", "cta": post.get("cta", ""), "hook": post["hook"], "n": total, "total": total, "handle": handle})
    return slides


def render_html(template: str, slide: dict, theme: dict | None = None) -> str:
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
    t = env.get_template(f"{template}.html")
    th = {**DEFAULT_THEME, **(theme or {})}
    return t.render(slide=slide, theme=th, font_url=FONT.resolve().as_uri(), width=WIDTH, height=HEIGHT)


def render_cards(post: dict, out_dir: Path, *, template: str, theme: dict | None, handle: str,
                 progress=print) -> list[Path]:
    """슬라이드마다 JPEG 를 만든다. 반환: 파일 경로 목록(순서대로)."""
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    slides = build_slides(post, handle)
    paths: list[Path] = []
    with sync_playwright() as pw:
        browser = _launch(pw)
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
        for slide in slides:
            html = render_html(template, slide, theme)
            page.set_content(html, wait_until="load")
            page.wait_for_function("document.fonts.status === 'loaded'")
            page.evaluate("window.__fit && window.__fit()")   # 글자 넘침 자동 축소
            path = out_dir / f"{slide['n']:02d}.jpg"
            page.screenshot(path=str(path), type="jpeg", quality=92, full_page=False)
            paths.append(path)
            progress(f"카드 {slide['n']}/{slide['total']} 저장")
        browser.close()
    (out_dir / "slides.json").write_text(json.dumps(slides, ensure_ascii=False, indent=1), encoding="utf-8")
    return paths


def _launch(pw):
    """이 PC 는 시스템 Chrome, 서버는 Playwright Chromium. 둘 다 없으면 오류가 그대로 난다."""
    try:
        return pw.chromium.launch(channel="chrome")
    except Exception:  # noqa: BLE001
        return pw.chromium.launch()


def preview_strip(paths: list[Path], out: Path, thumb_w: int = 360) -> Path:
    """검토용: 카드를 가로로 이어 붙인 한 장."""
    from PIL import Image

    ims = [Image.open(p) for p in paths]
    ratio = thumb_w / WIDTH
    th = int(HEIGHT * ratio)
    strip = Image.new("RGB", (thumb_w * len(ims), th), "white")
    for i, im in enumerate(ims):
        strip.paste(im.resize((thumb_w, th)), (i * thumb_w, 0))
    strip.save(out, quality=85)
    return out
