"""영상 소재(insta_video) — 영상 주소 찾기, 릴스 크기 필터, 출처 문구. ffmpeg 가 있으면 실제 변환도 한 번."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import insta_video as video  # noqa: E402


def test_find_video_prefers_link_then_text_then_page(monkeypatch):
    yt = "https://www.youtube.com/shorts/4bGb2OjU5tA"
    assert video.find_video({"link": yt}) == {"url": yt, "kind": "youtube", "page": yt}
    x = "https://x.com/sharifshameem/status/2096847916837314853"
    got = video.find_video({"link": "https://www.therundown.ai/p/astra", "summary": f"Sharif posted it: {x}?s=20 — wild."}, scan_official=False)
    assert got and got["kind"] == "x" and got["url"].startswith(x)
    # 인스타그램 영상 링크는 받을 수 없으니 건너뛴다
    assert video.find_video({"link": "https://www.instagram.com/reel/DdGyUaKASJl/", "summary": "https://www.instagram.com/reel/X/"}, scan_official=False) is None
    # 공식 페이지 안의 <video>/webm/유튜브 embed
    html = ('<video src="https://storage.googleapis.com/x/figure.webm#t=0.1" poster="p.jpg"></video>'
            '<iframe src="https://www.youtube.com/embed/U0aToL5C-bQ"></iframe>')

    class R:
        ok, text = True, html

    monkeypatch.setattr(video.requests if hasattr(video, "requests") else __import__("requests"), "get", lambda *a, **k: R())
    urls = video.scan_page("https://deepmind.google/blog/a/")
    assert urls[0] == "https://storage.googleapis.com/x/figure.webm" and "U0aToL5C-bQ" in urls[1] and video.kind_of(urls[1]) == "youtube"
    assert video.find_video({"link": "https://deepmind.google/blog/a/"})["kind"] == "file"


def test_video_filter_and_credit():
    assert video.video_filter(1920, 1080).startswith("scale=1080:-2,pad=1080:1920")
    assert video.video_filter(1080, 1920).startswith("scale=1080:1920:force_original_aspect_ratio=increase,crop")
    assert video.credit_text({"url": "https://x.com/sharifshameem/status/1", "uploader_id": "sharifshameem"}) == "Source · @sharifshameem / X"
    assert video.credit_text({"url": "https://www.youtube.com/shorts/abc", "uploader": "OpenAI"}) == "Source · OpenAI / YouTube"
    assert video.credit_text({"url": "https://storage.googleapis.com/x/a.webm", "page": "https://deepmind.google/blog/a/"}) == "Source · deepmind.google"
    assert video.kind_of("https://cdn.site/v.mp4?x=1") == "file" and video.is_video_site("https://youtu.be/dQw4w9WgXcQ")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 없음")
def test_make_reel_outputs_1080x1920_with_overlay(tmp_path, monkeypatch):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=4", str(src)], check=True)
    # 오버레이는 브라우저 없이도 돌게 투명 PNG 로 대체
    from PIL import Image

    def fake_overlay(out, **kw):
        Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)).save(out)
        return out

    monkeypatch.setattr(video, "render_overlay", fake_overlay)
    res = video.make_reel(src, tmp_path / "reel.mp4", title="t", credit="Source · test", max_seconds=3)
    info = video.probe(res["path"])
    assert (info["width"], info["height"]) == (1080, 1920) and info["has_audio"] and 2.5 <= info["duration"] <= 3.2
