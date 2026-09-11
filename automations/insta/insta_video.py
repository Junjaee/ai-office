"""영상 소재 → 릴스. 소재에 딸린 영상을 찾아(공식 유튜브·X·공식 페이지의 mp4/webm) 내려받고, 1080×1920 릴스(≤90초)로 만든다.

규칙(사용자 결정 2026-09-12): 남의 영상은 **출처를 화면과 캡션에 표기**하고 쓴다(`Source · @이름 / X`, `Source · OpenAI / YouTube`).
원작자가 문제 삼으면 내린다. 인스타그램 게시물의 영상은 로그인 없이는 받을 수 없어(2026-09-12 확인) 여기서는 시도하지 않는다.

도구: yt-dlp(유튜브·X·틱톡·비메오 등), ffmpeg/ffprobe(변환), Playwright(제목·출처 오버레이 PNG). 셋 중 하나라도 없으면 영상 없이 카드로 간다.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REEL_W, REEL_H = 1080, 1920
MAX_SOURCE_SECONDS = 300      # 이보다 긴 영상은 릴스 소재로 안 쓴다 (앞부분만 자르면 맥락이 끊김)
MAX_REEL_SECONDS = 90         # 릴스 길이 상한
MIN_REEL_SECONDS = 3

VIDEO_SITE_RE = re.compile(r"https?://(?:www\.|m\.|mobile\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)[\w-]{11}|youtu\.be/[\w-]{11}"
                           r"|(?:x|twitter)\.com/\w+/status/\d+|tiktok\.com/@[\w.]+/video/\d+|vimeo\.com/\d+)[^\s\"'<>]*")
FILE_RE = re.compile(r"https?://[^\s\"'<>\\]+?\.(?:mp4|webm|mov)(?:\?[^\s\"'<>\\]*)?")
YT_EMBED_RE = re.compile(r"(?:youtube\.com/embed/|youtube-nocookie\.com/embed/)([\w-]{11})")
INSTAGRAM_RE = re.compile(r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels)/[\w-]+")


def is_video_site(url: str) -> bool:
    return bool(VIDEO_SITE_RE.match((url or "").strip()))


def kind_of(url: str) -> str:
    u = (url or "").lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "x.com" in u or "twitter.com" in u:
        return "x"
    if "tiktok.com" in u:
        return "tiktok"
    if "instagram.com" in u:
        return "instagram"
    if FILE_RE.match(url or ""):
        return "file"
    return "other"


def find_in_text(text: str) -> list[str]:
    """글 속의 영상 주소(유튜브·X·틱톡·비메오·mp4) — 나온 순서, 중복 제거."""
    out: list[str] = []
    for m in list(VIDEO_SITE_RE.finditer(text or "")) + list(FILE_RE.finditer(text or "")):
        u = m.group(0).rstrip(".,);]")
        if u not in out:
            out.append(u)
    for vid in YT_EMBED_RE.findall(text or ""):
        u = f"https://www.youtube.com/watch?v={vid}"
        if u not in out:
            out.append(u)
    return out


def scan_page(url: str, *, timeout: int = 30) -> list[str]:
    """공식 페이지 HTML 에서 <video>/<source>/mp4·webm/유튜브 embed 주소를 찾는다. 실패하면 빈 목록."""
    import requests

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36",
                                       "Accept-Language": "en-US,en;q=0.9"}, timeout=timeout)
        if not r.ok:
            return []
    except Exception:  # noqa: BLE001
        return []
    body = r.text
    out: list[str] = []
    for m in re.finditer(r"<(?:video|source)[^>]+src=[\"']([^\"']+)[\"']", body):
        u = m.group(1).split("#")[0]
        if u.startswith("//"):
            u = "https:" + u
        if u.startswith("http") and u not in out:
            out.append(u)
    for u in find_in_text(body):
        if u not in out:
            out.append(u)
    # 포스터·썸네일 같은 이미지가 아닌 것만, 그리고 페이지 자기 자신은 제외
    return [u for u in out if u != url and kind_of(u) != "other"]


def find_video(cand: dict, *, scan_official: bool = True) -> dict | None:
    """소재에서 쓸 영상 하나를 고른다. 순서: 링크 자체가 영상 → 본문 속 영상 링크 → (공식 페이지면) 페이지 안의 영상.
    반환: {"url", "kind", "page"}  없으면 None. 인스타그램 영상은 받을 수 없어 None."""
    link = str(cand.get("link") or "")
    if is_video_site(link):
        return {"url": link, "kind": kind_of(link), "page": link}
    art = cand.get("article") or {}
    text = " ".join(str(x) for x in (cand.get("summary", ""), art.get("text", ""), art.get("html", "")))
    for u in find_in_text(text):
        if kind_of(u) != "instagram":
            return {"url": u, "kind": kind_of(u), "page": link}
    if scan_official and link.startswith("http") and not INSTAGRAM_RE.match(link):
        for u in scan_page(link):
            return {"url": u, "kind": kind_of(u), "page": link}
    return None


# ───────────────────────── 받기 ─────────────────────────

def tools_ok() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def probe(path: Path | str) -> dict:
    """ffprobe → {"duration", "width", "height", "has_audio"}."""
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)],
                       capture_output=True, text=True, check=True)
    info = json.loads(r.stdout or "{}")
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    a = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    dur = float(info.get("format", {}).get("duration") or v.get("duration") or 0)
    w, h = int(v.get("width") or 0), int(v.get("height") or 0)
    rot = 0
    for sd in v.get("side_data_list", []) or []:
        if "rotation" in sd:
            rot = int(abs(float(sd["rotation"])))
    if rot in (90, 270):
        w, h = h, w
    return {"duration": dur, "width": w, "height": h, "has_audio": a}


def download(url: str, out_dir: Path, *, max_seconds: int = MAX_SOURCE_SECONDS, progress=print) -> dict:
    """영상을 out_dir/source.<ext> 로 받는다(mp4·webm 직접 주소는 그대로 받고, 그 외는 yt-dlp). 반환: {path, url, title, uploader, uploader_id, duration, page}.
    너무 길거나 못 받으면 RuntimeError."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if kind_of(url) == "file":
        import requests

        path = out_dir / ("source" + Path(url.split("?")[0]).suffix.lower())
        with requests.get(url, stream=True, timeout=60, headers={"User-Agent": "Mozilla/5.0"}) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        meta = {"path": str(path), "url": url, "title": "", "uploader": "", "uploader_id": "", "page": url}
    else:
        import yt_dlp  # type: ignore
        from yt_dlp.utils import match_filter_func  # type: ignore

        opts: dict = {"outtmpl": str(out_dir / "source.%(ext)s"), "format": "bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[height<=1080]/b",
                      "merge_output_format": "mp4", "noplaylist": True, "quiet": True, "no_warnings": True}
        if max_seconds:
            opts["match_filter"] = match_filter_func(f"duration <= {max_seconds}")
        with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(url, download=True) or {}
        dur = float(info.get("duration") or 0)
        if dur and max_seconds and dur > max_seconds:
            raise RuntimeError(f"영상이 너무 깁니다 ({int(dur)}초 > {max_seconds}초)")
        path = next((p for p in out_dir.glob("source.*") if p.suffix.lower() in (".mp4", ".webm", ".mkv", ".mov")), None)
        if not path:
            raise RuntimeError("받은 영상 파일이 없습니다 (길이 제한에 걸렸을 수 있음)")
        meta = {"path": str(path), "url": url, "title": str(info.get("title") or "")[:120], "uploader": str(info.get("uploader") or info.get("channel") or ""),
                "uploader_id": str(info.get("uploader_id") or "").lstrip("@"), "page": str(info.get("webpage_url") or url)}
    pr = probe(meta["path"])
    if pr["duration"] and pr["duration"] > max_seconds:
        raise RuntimeError(f"영상이 너무 깁니다 ({int(pr['duration'])}초)")
    meta.update(pr)
    progress(f"영상 받음 {pr['width']}×{pr['height']} {pr['duration']:.0f}초 — {url[:60]}")
    return meta


def credit_text(meta: dict) -> str:
    """화면·캡션에 찍을 출처: 'Source · @이름 / X' · 'Source · OpenAI / YouTube' · 'Source · deepmind.google'."""
    k = kind_of(meta.get("url", ""))
    who = meta.get("uploader_id") or meta.get("uploader") or ""
    if k == "x":
        m = re.search(r"(?:x|twitter)\.com/(\w+)/status", meta.get("url", ""))
        who = "@" + (m.group(1) if m else who.lstrip("@"))
        return f"Source · {who} / X"
    if k == "youtube":
        return f"Source · {meta.get('uploader') or who or 'YouTube'} / YouTube"
    if k == "tiktok":
        return f"Source · @{who.lstrip('@')} / TikTok"
    host = re.sub(r"^https?://(www\.)?", "", meta.get("page") or meta.get("url", "")).split("/")[0]
    return f"Source · {host}"


# ───────────────────────── 릴스 만들기 ─────────────────────────

def video_filter(width: int, height: int, bg: str = "#15171c") -> str:
    """원본 크기 → 1080×1920 채우기: 세로·정사각은 꽉 채워 자르고, 가로는 폭을 맞추고 위아래를 배경색으로 채운다."""
    if height >= width:
        return f"scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,crop={REEL_W}:{REEL_H},setsar=1"
    return f"scale={REEL_W}:-2,pad={REEL_W}:{REEL_H}:(ow-iw)/2:(oh-ih)/2:color={bg},setsar=1"


def render_overlay(out: Path, *, title: str, credit: str, brand: str, handle: str, sub: str = "", theme: dict | None = None) -> Path:
    """제목·브랜드·출처를 얹을 투명 PNG(1080×1920). 카드와 같은 글꼴·색."""
    from playwright.sync_api import sync_playwright

    import insta_cards as cards

    html = cards.render_html("reel_overlay", {"title": title, "sub": sub, "credit": credit, "brand": brand, "handle": handle,
                                              "kind": "overlay"}, theme, width=REEL_W, height=REEL_H)
    with sync_playwright() as pw:
        browser = cards._launch(pw)
        page = browser.new_page(viewport={"width": REEL_W, "height": REEL_H}, device_scale_factor=1)
        page.set_content(html, wait_until="load")
        page.wait_for_function("document.fonts.status === 'loaded'")
        page.evaluate("window.__fit && window.__fit()")
        page.screenshot(path=str(out), type="png", omit_background=True, full_page=False)
        browser.close()
    return out


def make_reel(src: Path | str, out: Path, *, title: str, credit: str, brand: str = "AI TIPS", handle: str = "", sub: str = "",
              theme: dict | None = None, max_seconds: int = MAX_REEL_SECONDS, progress=print) -> dict:
    """원본 영상 + 오버레이 → out (mp4, H.264/AAC, 1080×1920, 30fps, ≤max_seconds). 반환: {path, duration, overlay}."""
    if not tools_ok():
        raise RuntimeError("ffmpeg/ffprobe 가 없습니다")
    src = Path(src)
    info = probe(src)
    if info["duration"] and info["duration"] < MIN_REEL_SECONDS:
        raise RuntimeError("영상이 너무 짧습니다")
    overlay = render_overlay(out.with_name("overlay.png"), title=title, credit=credit, brand=brand, handle=handle, sub=sub, theme=theme)
    bg = (theme or {}).get("bg", "#15171c")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-i", str(overlay)]
    if not info["has_audio"]:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    cmd += ["-filter_complex", f"[0:v]{video_filter(info['width'], info['height'], bg)},fps=30[v0];[v0][1:v]overlay=0:0:format=auto[v]",
            "-map", "[v]", "-map", "0:a:0" if info["has_audio"] else "2:a:0",
            "-t", str(max_seconds), "-c:v", "libx264", "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p", "-crf", "22",
            "-preset", "medium", "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-movflags", "+faststart", "-shortest", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    done = probe(out)
    progress(f"릴스 완성 {done['width']}×{done['height']} {done['duration']:.0f}초")
    return {"path": str(out), "duration": done["duration"], "overlay": str(overlay)}


def thumbnail(video: Path | str, out: Path, at: float = 1.0) -> Path:
    """검토용 대표 화면 한 장."""
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", str(video), "-frames:v", "1", "-q:v", "3", str(out)],
                   check=True, capture_output=True, text=True)
    return out
