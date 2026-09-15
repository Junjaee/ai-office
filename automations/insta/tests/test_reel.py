"""릴스 v2(insta_reel): 말하는 대본 정리, 자막 묶기, 강조어, 댓글 키워드 고정, (ffmpeg 있으면) 실제 조립."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import insta_reel as reel  # noqa: E402

SCRIPT = {"hook": {"say": "제미나이(Gemini) 쓰려고 탭 뒤지지 마세요", "big": "탭 대신 단축키"},
          "segments": [{"say": "Alt 키랑 스페이스바면 바로 떠요.", "big": "Alt 스페이스", "keywords": ["스페이스바"], "card": 1},
                       {"say": "설치는 무료입니다.", "big": "무료 설치", "card": 0},
                       {"say": "지메일·드라이브도 찾아 줘요.", "big": "메일 속 정보", "keywords": ["지메일"], "card": 0}],
          "cta": {"say": "저장해 두세요.", "big": "저장"}}


def test_parts_and_speech_cleanup():
    parts = reel.parts_of(SCRIPT)
    assert [p["kind"] for p in parts] == ["hook", "seg", "seg", "seg", "cta"]
    assert "(Gemini)" not in parts[0]["say"] and parts[0]["say"].startswith("제미나이 쓰려고")
    assert parts[3]["say"].startswith("지메일, 드라이브도")


def test_chunk_words_and_keyword_highlight():
    words = [(0.0, 0.3, "구글이"), (0.3, 0.6, "제미나이"), (0.6, 0.9, "윈도우"), (0.9, 1.2, "앱을"), (1.2, 1.5, "내놨거든요.")]
    chunks = reel.chunk_words(words, max_chars=13)
    assert all(len(c[2]) <= 13 or " " not in c[2] for c in chunks) and chunks[0][0] == 0.0 and chunks[-1][2].endswith("내놨거든요.")
    assert reel._is_key("앱을", ["윈도우 앱"]) and reel._is_key("지메일이랑", ["지메일"])
    assert not reel._is_key("구글이", ["윈도우 앱"]) and not reel._is_key("앱스토어에서", ["앱"])


def test_enforce_cta_keeps_dm_keyword_exact():
    fixed = reel.enforce_cta({**SCRIPT, "cta": {"say": "댓글에 '제미나이' 남기면 보내드려요", "big": "x"}}, "단축키")
    assert "'단축키'" in fixed["cta"]["say"] and fixed["cta"]["big"] == "댓글에 '단축키'"
    same = reel.enforce_cta({**SCRIPT, "cta": {"say": "댓글에 '단축키' 남기면 설치 주소 보내드려요", "big": "댓글"}}, "단축키")
    assert same["cta"]["say"].endswith("설치 주소 보내드려요")
    assert reel.enforce_cta(SCRIPT, "") is SCRIPT


def test_prompt_mentions_spoken_rules_and_keyword():
    s, u = reel.script_prompt("AI 꿀팁", "직장인", {"title": "t", "subtitle": "s", "paragraphs": [{"heading": "h", "text": "x"}]},
                              [{"kind": "cover", "title": "표지", "image_path": "a.jpg"}, {"kind": "cta", "title": "끝"}], dm_keyword="단축키")
    assert "합쇼체" in s and "'단축키' 그대로" in s and "0. [cover] 표지 (사진 있음)" in u and "[cta]" not in u


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 없음")
def test_build_with_voice_and_music_and_silent(tmp_path):
    def fake_speaker(text, out_wav):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1.0", "-ar", "48000", str(out_wav)], check=True)

    theme = {"bg": "#fff7f0", "fg": "#2b2420", "accent": "#ff8a5b"}          # 밝은 테마도 깨지지 않는지
    voiced = reel.build(SCRIPT, tmp_path / "v.mp4", theme=theme, engine="supertonic", supertonic=fake_speaker, bgm=True, progress=lambda m: None)
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type", "-of", "csv=p=0", voiced["path"]],
                          capture_output=True, text=True).stdout
    assert "1080,1920" in info and "audio" in info
    assert 5.0 <= voiced["duration"] <= 7.8, voiced["duration"]              # 1초×5구간 + 쉼
    silent = reel.build(SCRIPT, tmp_path / "s.mp4", theme=theme, engine=None, bgm=True, progress=lambda m: None)
    assert silent["duration"] >= 5 * 2.2 - 0.5


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 없음")
def test_paid_voice_failure_falls_back_to_edge(tmp_path, monkeypatch):
    """타입캐스트 크레딧이 떨어져도 릴스는 엣지 음성으로 끝까지 만들어진다(한 편 안에서 목소리가 섞이지 않게 전부 다시)."""
    def broken(*a, **k):
        raise RuntimeError("HTTP 402 크레딧 부족")

    async def fake_edge(text, voice, rate, out):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=0.8", str(out)], check=True)
        return []

    monkeypatch.setattr(reel, "typecast_tts", broken)
    monkeypatch.setattr(reel, "_edge", fake_edge)
    logs = []
    parts = reel.parts_of(SCRIPT)
    used = reel.speak(parts, tmp_path, engine="typecast", voice="tc_x", progress=logs.append)
    assert used == "edge" and all(p["audio"].endswith(".mp3") and p["dur"] > 0.5 for p in parts)
    assert any("엣지 음성으로 대신" in m for m in logs)
    with pytest.raises(RuntimeError):                                   # 무료 엔진 오류는 숨기지 않는다
        monkeypatch.setattr(reel, "_edge", lambda *a: (_ for _ in ()).throw(RuntimeError("x")))
        reel.speak(reel.parts_of(SCRIPT), tmp_path / "e", engine="edge")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 없음")
def test_tighten_shortens_long_pause_but_keeps_speech(tmp_path):
    """3초 소리 중 0.8~2.0초를 무음으로 만든 파일: 1.2초 쉼이 0.32초로 줄어 약 2.1초가 된다."""
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=3",
                    "-af", "volume=enable='between(t,0.8,2.0)':volume=0", str(wav)], check=True)
    before = reel.duration_of(wav)
    reel.tighten(wav)
    after = reel.duration_of(wav)
    assert 2.9 <= before <= 3.1 and 1.8 <= after <= 2.5, (before, after)
    assert not (tmp_path / "a_t.wav").exists()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 없음")
def test_build_over_source_video_loops_and_shows_video(tmp_path):
    """영상 해설형: 원본(3초)이 해설 길이만큼 반복되고, 가운데 상자에 원본이 비친다(검은 화면 아님)."""
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=30:duration=3", str(src)], check=True)

    def fake_speaker(text, out_wav):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1.0", "-ar", "48000", str(out_wav)], check=True)

    res = reel.build(SCRIPT, tmp_path / "v.mp4", theme={}, engine="supertonic", supertonic=fake_speaker, bgm=True,
                     video={"path": str(src), "credit": "Source · u/test / Reddit"}, progress=lambda m: None)
    assert 5.0 <= res["duration"] <= 7.8, res["duration"]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "4.5", "-i", res["path"], "-frames:v", "1", "-vf", "crop=600:300:240:810,scale=60:30",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    assert len(raw) == 1800 and sum(raw) / len(raw) > 60, sum(raw) / max(len(raw), 1)


def test_video_chain_vertical_fills_screen_and_landscape_uses_box():
    assert "boxblur" not in reel.video_chain(720, 1280) and "crop=1080:1920" in reel.video_chain(720, 1280)
    assert "boxblur" in reel.video_chain(1920, 1080) and "boxblur" in reel.video_chain(720, 720)
