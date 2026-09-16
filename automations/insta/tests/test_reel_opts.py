"""계정 설정의 릴스 말 빠르기·감정이 목소리 엔진 옵션으로 넘어가는지."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_insta  # noqa: E402


def test_reel_tts_opts_from_account_settings():
    assert run_insta.reel_tts_opts({"reel_tempo": 1.25}, "typecast") == {"tempo": 1.25, "emotion": "normal"}
    assert run_insta.reel_tts_opts({"reel_emotion": "toneup"}, "typecast") == {"tempo": 1.1, "emotion": "toneup"}
    assert run_insta.reel_tts_opts({"reel_tempo": 1.2}, "google") == {"rate": 1.2}
    assert run_insta.reel_tts_opts({"reel_tempo": 1.2}, "edge") is None


def test_policy_config_is_faster_piljae():
    import yaml

    acct = yaml.safe_load((Path(run_insta.__file__).parent / "config.actions.yaml").read_text(encoding="utf-8"))["accounts"]["policy"]
    assert acct["reel_voice_engine"] == "typecast" and float(acct["reel_tempo"]) > 1.1
