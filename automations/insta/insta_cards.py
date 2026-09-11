"""카드 제작 — 카드 계획(JSON: 표지·카드별 요약·사진) + HTML 템플릿 → 1080×1350 JPEG 여러 장 (Playwright).

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
MIN_IMAGE_WIDTH = 480      # 이보다 좁은 사진은 카드에 넣지 않는다

DEFAULT_THEME = {
    "bg": "#15171c", "fg": "#f5f6f8", "muted": "#9aa3b2", "accent": "#f2b544", "card": "#1f2229",
    "code_bg": "#0d0f13", "brand": "",
}


def build_slides(plan: dict, handle: str) -> list[dict]:
    """카드 계획(표지·카드·cta) → 슬라이드 목록. image 는 후보 dict(url·source_url…) 그대로 두고 렌더 때 파일로 바꾼다."""
    body = plan.get("cards", [])
    total = len(body) + 2
    cover = plan.get("cover", {})
    slides = [{"kind": "cover", "title": cover.get("title", ""), "sub": cover.get("sub", ""), "n": 1, "total": total,
               "handle": handle, "image": cover.get("image") or None, "image_caption": "",
               "category": cover.get("category", ""), "fallbacks": list(cover.get("fallbacks") or []),
               "mock": cover.get("mock")}]
    for i, c in enumerate(body, start=2):
        slides.append({"kind": "body", "title": c.get("title", ""), "lines": list(c.get("lines", [])),
                       "prompt": c.get("prompt", ""), "mock": c.get("mock"),
                       "keyword": c.get("keyword", ""), "highlights": list(c.get("highlights") or []),
                       "image": c.get("image") or None, "image_caption": c.get("image_caption", ""),
                       "n": i, "total": total, "handle": handle, "idx": i - 1})
    slides.append({"kind": "cta", "cta": plan.get("cta", ""), "title": cover.get("title", ""), "n": total, "total": total,
                   "handle": handle, "image": None})
    return slides


def credit_of(image: dict | None) -> str:
    """사진 출처 표시 문구: '사진: 출처 도메인' (공식 페이지 캡처면 '화면: 도메인', CC 사진이면 '사진: 작가 · CC BY')."""
    if not image:
        return ""
    import re

    if image.get("kind") == "cc":
        return "사진: " + str(image.get("source_title") or "CC")
    host = re.sub(r"^https?://(www\.)?", "", str(image.get("source_url") or image.get("url") or "")).split("/")[0]
    return ("화면: " if image.get("kind") == "screenshot" else "사진: ") + host


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


BRAND = "AI TIPS"          # 카드 위 브랜드 라벨 (ai.trend.kr 의 'AI TREND' 처럼)


def mark_highlights(line: str, highlights: list[str]):
    """문장 안의 강조어를 <b class="hl"> 로 감싼다(나머지는 HTML 이스케이프). 템플릿에 안전한 Markup 으로 돌려준다."""
    import html as _html

    from markupsafe import Markup

    out = _html.escape(line)
    for h in sorted({h for h in highlights if h}, key=len, reverse=True):
        out = out.replace(_html.escape(h), f'<b class="hl">{_html.escape(h)}</b>')
    return Markup(out)


def render_html(template: str, slide: dict, theme: dict | None = None, *, width: int = WIDTH, height: int = HEIGHT) -> str:
    """슬라이드 하나를 HTML 로. slide['image'] 가 로컬 파일 경로면 data URI 로 바꿔 넣는다."""
    global _FONT_URI
    if _FONT_URI is None:
        _FONT_URI = data_uri(FONT) if FONT.exists() else ""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html"]))
    t = env.get_template(f"{template}.html")
    th = {**DEFAULT_THEME, **(theme or {})}
    view = dict(slide)
    view["lines_html"] = [mark_highlights(ln, view.get("highlights") or []) for ln in view.get("lines") or []]
    m = view.get("mock")
    if m:
        view["mock_rows"] = [[c.strip() for c in ln.split("|")] for ln in m["assistant"]]
        view["mock_is_table"] = all(len(r) >= 2 for r in view["mock_rows"]) and len(view["mock_rows"]) >= 2
    view.setdefault("brand", BRAND)
    img = view.get("image")
    view["credit"] = view.get("credit") or (credit_of(img) if isinstance(img, dict) else "")
    path = view.get("image_path") or (img if isinstance(img, str) else "")
    view["image"] = data_uri(path) if path and Path(path).exists() else ""
    return t.render(slide=view, theme=th, font_url=_FONT_URI, width=width, height=height)


def render_cards(plan: dict, out_dir: Path, *, template: str, theme: dict | None, handle: str,
                 progress=print) -> list[Path]:
    """슬라이드마다 JPEG 를 만든다. 반환: 파일 경로 목록(순서대로)."""
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    slides = build_slides(plan, handle)
    paths: list[Path] = []
    with sync_playwright() as pw:
        browser = _launch(pw)
        media_dir = out_dir / "media"
        for slide in slides:
            tries = [slide.get("image")] + (list(slide.get("fallbacks") or []) if slide["kind"] == "cover" else [])
            slide["image"], slide["image_path"] = None, ""
            for k, img in enumerate(x for x in tries if x):
                ref = img["url"] if isinstance(img, dict) else str(img)
                path = prepare_image(browser, ref, media_dir, f"{slide['n']:02d}{'' if k == 0 else chr(96 + k)}", progress)
                if path:
                    slide["image"], slide["image_path"] = img, path
                    slide["credit"] = credit_of(img) if isinstance(img, dict) else ""
                    break
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
                                  locale="ko-KR", extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"})
            try:
                pg.goto(url, wait_until="domcontentloaded", timeout=40000)
            except Exception:  # noqa: BLE001 — 무거운 페이지는 커밋 시점까지만 기다리고 캡처한다
                pg.goto(url, wait_until="commit", timeout=40000)
            pg.wait_for_timeout(2500)
            _dismiss_banners(pg)
            pg.wait_for_timeout(800)
            blocked = _blocked_page(pg)
            path = media_dir / f"{stem}.png"
            pg.screenshot(path=str(path), full_page=False)
            pg.close()
            if blocked or _is_blank(path):
                path.unlink(missing_ok=True)
                progress(f"캡처 제외({'봇 확인·차단 페이지' if blocked else '빈 화면'}) {url[:50]}")
                return ""
            progress(f"화면 캡처 {url}")
            return str(path.resolve())
        r = requests.get(ref, headers={"User-Agent": "Mozilla/5.0 (ai-office-insta)"}, timeout=30)
        r.raise_for_status()
        ext = ".png" if "png" in r.headers.get("content-type", "") else ".jpg"
        path = media_dir / f"{stem}{ext}"
        path.write_bytes(r.content)
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
            if w < MIN_IMAGE_WIDTH or h < 240:
                path.unlink(missing_ok=True)
                progress(f"이미지가 작아 제외({w}×{h}) {ref[:50]}")
                return ""
            if _is_blank_image(im):
                path.unlink(missing_ok=True)
                progress(f"이미지가 거의 비어 있어 제외 {ref[:50]}")
                return ""
            if im.mode not in ("RGB", "L"):        # PNG 투명·팔레트 → JPEG 로 정리
                im.convert("RGB").save(path.with_suffix(".jpg"), quality=90)
                if path.suffix != ".jpg":
                    path.unlink(missing_ok=True)
                path = path.with_suffix(".jpg")
        progress(f"이미지 받음 {w}×{h} {ref[:50]}")
        return str(path.resolve())
    except Exception as exc:  # noqa: BLE001
        progress(f"이미지 실패({type(exc).__name__}) — 글만 있는 카드로")
        return ""


_BLOCK_RE = r"사람인지 확인|just a moment|verify you are human|are you a robot|access denied|attention required|captcha|cloudflare|enable javascript|403 forbidden|page not found|404"


def _blocked_page(pg) -> bool:
    """봇 확인·차단·오류 페이지인지 (제목 + 본문 앞부분으로 판단)."""
    import re

    try:
        title = pg.title() or ""
        body = pg.evaluate("() => (document.body && document.body.innerText || '').slice(0, 600)") or ""
    except Exception:  # noqa: BLE001
        return False
    text = f"{title}\n{body}"
    return bool(re.search(_BLOCK_RE, text, re.I)) and len(body) < 1200


def _is_blank_image(im) -> bool:
    """거의 단색(빈 페이지·흰 썸네일)인지: 회색조 표준편차가 작으면 빈 이미지로 본다."""
    from PIL import ImageStat

    g = im.convert("L")
    g.thumbnail((256, 256))
    return ImageStat.Stat(g).stddev[0] < 12


def _is_blank(path: Path) -> bool:
    from PIL import Image

    with Image.open(path) as im:
        return _is_blank_image(im)


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
