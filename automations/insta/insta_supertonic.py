"""Supertonic 3 (Supertone 오픈소스 TTS, 한국어 지원, CPU 로 돎) 호출 도우미 — insta_reel.build(supertonic=...) 에 넘길 함수를 만든다.

준비(서버에서는 워크플로가, 이 PC 에서는 한 번 손으로):
  git clone --depth 1 https://github.com/supertone-inc/supertonic.git <dir>
  pip install -r <dir>/py/requirements.txt
  python -c "from huggingface_hub import snapshot_download; snapshot_download('Supertone/supertonic-3', local_dir='<dir>/assets')"
환경변수 SUPERTONIC_DIR 로 위치를 알려 준다. 라이선스: BigScience Open RAIL-M (상업적 이용 가능, 사용 제한 조항 준수).
목소리: F1~F5(여성), M1~M5(남성). 단어 시각은 주지 않으므로 insta_reel 이 글자 수로 추정한다.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def available(root: str | None = None) -> bool:
    d = Path(root or os.environ.get("SUPERTONIC_DIR", ""))
    return bool(str(d)) and (d / "py" / "example_onnx.py").exists() and (d / "assets" / "onnx").exists()


def make_speaker(voice: str = "F1", speed: float = 1.15, steps: int = 8, root: str | None = None):
    """text, out_wav → 합성. 실패하면 RuntimeError."""
    d = Path(root or os.environ.get("SUPERTONIC_DIR", ""))
    if not available(str(d)):
        raise RuntimeError("Supertonic 이 준비되지 않았습니다 (SUPERTONIC_DIR)")

    def speak(text: str, out_wav: Path) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [sys.executable, "example_onnx.py", "--text", text, "--lang", "ko", "--voice-style", str(d / "assets" / "voice_styles" / f"{voice}.json"),
                   "--speed", str(speed), "--total-step", str(steps), "--n-test", "1", "--save-dir", tmp]
            r = subprocess.run(cmd, cwd=d / "py", capture_output=True, text=True, encoding="utf-8", errors="replace")
            wavs = sorted(Path(tmp).glob("*.wav"))
            if r.returncode != 0 or not wavs:
                raise RuntimeError(f"Supertonic 실패: {r.stderr[-200:]}")
            # 앞뒤 무음만 자른다. stop_periods 를 쓰면 문장 사이 쉼에서 뒤를 통째로 잘라 버리므로(2026-09-14 실측: 31초 → 15초),
            # 앞 무음 제거 → 뒤집기 → 앞 무음 제거 → 다시 뒤집기
            trim = "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wavs[0]), "-af",
                            f"{trim},areverse,{trim},areverse,aresample=48000", str(out_wav)], check=True)

    return speak
