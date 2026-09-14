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
                       {"say": "지메일·드라이브도 찾아 줘요.", "big": "메일 속 정보", "keywords": ["지메일"], "card": 0}],
          "cta": {"say": "저장해 두세요.", "big": "저장"}}


def test_parts_and_speech_cleanup():
    parts = reel.parts_of(SCRIPT)
    assert [p["kind"] for p in parts] == ["hook", "seg", "seg", "cta"]
    assert "(Gemini)" not in parts[0]["say"] and parts[0]["say"].startswith("제미나이 쓰려고")
    assert parts[2]["say"].startswith("지메일, 드라이브도")


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
    assert "구어체" in s and "'단축키' 그대로" in s and "0. [cover] 표지 (사진 있음)" in u and "[cta]" not in u


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg 없음")
def test_build_with_voice_and_music_and_silent(tmp_path):
    def fake_speaker(text, out_wav):
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300:duration=1.0", "-ar", "48000", str(out_wav)], check=True)

    theme = {"bg": "#fff7f0", "fg": "#2b2420", "accent": "#ff8a5b"}          # 밝은 테마도 깨지지 않는지
    voiced = reel.build(SCRIPT, tmp_path / "v.mp4", theme=theme, engine="supertonic", supertonic=fake_speaker, bgm=True, progress=lambda m: None)
    info = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type", "-of", "csv=p=0", voiced["path"]],
                          capture_output=True, text=True).stdout
    assert "1080,1920" in info and "audio" in info
    assert 4.0 <= voiced["duration"] <= 6.5, voiced["duration"]              # 1초×4구간 + 쉼
    silent = reel.build(SCRIPT, tmp_path / "s.mp4", theme=theme, engine=None, bgm=True, progress=lambda m: None)
    assert silent["duration"] >= 4 * 2.2 - 0.5
