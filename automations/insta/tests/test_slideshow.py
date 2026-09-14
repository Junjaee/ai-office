"""카드 → 나레이션 릴스(insta_slideshow): 나레이션 문장, ffmpeg 명령, (ffmpeg 있으면) 실제 변환. TTS 는 무음 mp3 로 대체."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import insta_slideshow as ss  # noqa: E402


def test_narration_text_per_slide_kind():
    assert ss.narration_for({"kind": "cover", "title": "제목 🔥", "sub": "부제"}) == "제목 부제"
    body = ss.narration_for({"kind": "body", "title": "소제목", "lines": ["첫 문장.", "둘째 문장."], "prompt": "표로 정리해 줘"})
    assert body.startswith("소제목 첫 문장. 둘째 문장.") and "입력 예시" in body
    assert ss.narration_for({"kind": "cta", "cta": "저장해 두세요"}) == "저장해 두세요"


def test_ffmpeg_command_shape(tmp_path):
    cmd = ss.ffmpeg_command([tmp_path / "1.jpg", tmp_path / "2.jpg"], [tmp_path / "a.mp3", tmp_path / "b.mp3"], [3.0, 4.5], tmp_path / "o.mp4")
    assert cmd[0] == "ffmpeg" and cmd.count("-loop") == 2 and "concat=n=2:v=1:a=0[v]" in cmd[cmd.index("-filter_complex") + 1]
    assert "-t" in cmd and str(tmp_path / "o.mp4") == cmd[-1]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 없음")
def test_build_makes_vertical_video_from_cards(tmp_path):
    cards = []
    for i in range(3):
        p = tmp_path / f"{i:02d}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x{'%02x' % (40 * i + 30)}3040:s=1080x1350", "-frames:v", "1", str(p)], check=True)
        cards.append(p)

    def fake_synth(texts, out_dir, *, voice, rate):
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        for i, _ in enumerate(texts):
            a = out_dir / f"nar{i:02d}.mp3"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1.2", "-b:a", "64k", str(a)], check=True)
            paths.append(a)
        return paths

    slides = [{"kind": "cover", "title": "t", "sub": "s"}, {"kind": "body", "title": "b", "lines": ["x"]}, {"kind": "cta", "cta": "c"}]
    res = ss.build(cards, slides, tmp_path / "reel.mp4", synth=fake_synth, progress=lambda m: None)
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type", "-of", "csv=p=0", res["path"]],
                          capture_output=True, text=True).stdout
    assert "1080,1920" in info and "audio" in info
    assert 6.0 <= res["duration"] <= 8.5, res["duration"]      # 3.0 + 1.8 + 1.8 ≈ 6.6초
