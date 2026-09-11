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
    """원고 → 슬라이드 목록 (표지, 본문 n, 마무리). image 는 준비된 로컬 파일 경로로 바뀐다."""
    body = post.get("slides", [])
    total = len(body) + 2
    slides = [{"kind": "cover", "hook": post["hook"], "sub": post.get("sub", ""), "n": 1, "total": total, "handle": handle,
               "image": post.get("cover_image", "")}]
    for i, s in enumerate(body, start=2):
        slides.append({"kind": "body", "title": s.get("title", ""), "body": s.get("body", ""),
                       "code": s.get("code", ""), "image": s.get("image", ""), "image_caption": s.get("image_caption", ""),
                       "n": i, "total": total, "handle": handle, "idx": i - 1})
    slides.append({"kind": "cta", "cta": post.get("cta", ""), "hook": post["hook"], "n": total, "total": total, "handle": handle})
    return slides


def data_uri(path: Path | str) -> str:
    """파일 → data: URI. set_content 로 연 페이지(about:blank)는 file:// 자원을 막으므로 HTML 에 직접 심는다."""
    import base64
    import mimetypes

    path = Path(path)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix == ".woff2":
        mime = "font/woff2"
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


_FONT_URI: str | None = None


def render_html(template: str, slide: dict, theme: dict | None = None) -> str:
    """슬라이드 하나를 HTML 로. slide['image'] 가 로컬 파일 경로면 data URI 로 바꿔 넣는다."""
    global _FONT_URI
    if _FONT_URI is None:
        _FONT_URI = data_uri(FONT) if FONT.exists() else ""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
    t = env.get_template(f"{template}.html")
    th = {**DEFAULT_THEME, **(theme or {})}
    view = dict(slide)
    img = view.get("image") or ""
    if img and not img.startswith(("data:", "http")):
        view["image"] = data_uri(img) if Path(img).exists() else ""
    return t.render(slide=view, theme=th, font_url=_FONT_URI, width=WIDTH, height=HEIGHT)


def render_cards(post: dict, out_dir: Path, *, template: str, theme: dict | None, handle: str,
                 progress=print) -> list[Path]:
    """슬라이드마다 JPEG 를 만든다. 반환: 파일 경로 목록(순서대로)."""
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    slides = build_slides(post, handle)
    paths: list[Path] = []
    with sync_playwright() as pw:
        browser = _launch(pw)
        media_dir = out_dir / "media"
        for slide in slides:
            if slide.get("image"):
                slide["image"] = prepare_image(browser, slide["image"], media_dir, f"{slide['n']:02d}", progress)
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


def prepare_image(browser, ref: str, media_dir: Path, stem: str, progress=print) -> str:
    """image 값 → 카드에 넣을 로컬 파일 경로. 'screenshot:<url>' 은 그 페이지를 1440×900 으로 캡처(쿠키 배너는 닫거나 숨김), 그 외는 이미지 다운로드.
    실패하면 빈 문자열(이미지 없는 카드로 렌더)."""
    import requests

    media_dir.mkdir(parents=True, exist_ok=True)
    try:
        if ref.startswith("screenshot:"):
            url = ref[len("screenshot:"):].strip()
            pg = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1,
                                  locale="ko-KR")
            pg.goto(url, wait_until="networkidle", timeout=45000)
            _dismiss_banners(pg)
            pg.wait_for_timeout(800)
            path = media_dir / f"{stem}.png"
            pg.screenshot(path=str(path), full_page=False)
            pg.close()
            progress(f"화면 캡처 {url}")
            return str(path.resolve())
        r = requests.get(ref, headers={"User-Agent": "Mozilla/5.0 (ai-office-insta)"}, timeout=30)
        r.raise_for_status()
        ext = ".png" if "png" in r.headers.get("content-type", "") else ".jpg"
        path = media_dir / f"{stem}{ext}"
        path.write_bytes(r.content)
        progress(f"이미지 받음 {ref[:60]}")
        return str(path.resolve())
    except Exception as exc:  # noqa: BLE001
        progress(f"이미지 실패({type(exc).__name__}) — 글만 있는 카드로")
        return ""


_BANNER_BUTTON = r"동의|확인|닫기|accept|agree|got it|ok\b|allow|dismiss|close"
_BANNER_CSS = ("[class*='cookie' i], [id*='cookie' i], [class*='consent' i], [id*='consent' i], "
               "[aria-label*='cookie' i], [class*='gdpr' i], [id*='gdpr' i] { display: none !important; }")


def _dismiss_banners(pg) -> None:
    """쿠키·동의 배너를 최대한 치운다: 동의 버튼을 눌러 보고, 못 누르면 CSS 로 숨긴다. 실패해도 캡처는 계속."""
    import re

    try:
        btn = pg.get_by_role("button", name=re.compile(_BANNER_BUTTON, re.I)).first
        btn.click(timeout=1500)
        pg.wait_for_timeout(500)
    except Exception:  # noqa: BLE001
        pass
    try:
        pg.add_style_tag(content=_BANNER_CSS)
    except Exception:  # noqa: BLE001
        pass


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
