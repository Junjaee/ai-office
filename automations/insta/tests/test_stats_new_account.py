"""게시물이 하나도 없는 새 계정(폴더 없음)에서도 지표 수집이 stats.json 을 만든다 (2026-09-15 parent 첫 실행 실패)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import insta_publisher as pub  # noqa: E402
import run_insta  # noqa: E402


class FakeIG:
    def __init__(self, token, user_id):
        pass

    def account(self):
        return {"username": "babyhoney.kr", "followers_count": 0, "follows_count": 0, "media_count": 0}


def test_stats_creates_folder_for_new_account(tmp_path, monkeypatch):
    posted = tmp_path / "data" / "insta" / "parent" / "posted.jsonl"      # 폴더도 파일도 없음
    monkeypatch.setattr(run_insta, "posted_path", lambda account: posted)
    monkeypatch.setattr(run_insta, "load_posted", lambda account: [])
    monkeypatch.setattr(run_insta, "commit_paths", lambda paths, msg: None)
    monkeypatch.setattr(pub, "account_env", lambda account: ("t", "u"))
    monkeypatch.setattr(pub, "Instagram", FakeIG)
    res = run_insta.do_stats({}, {}, SimpleNamespace(account="parent"), progress=lambda m: None)
    out = json.loads((posted.parent / "stats.json").read_text(encoding="utf-8"))
    assert out["account"]["username"] == "babyhoney.kr" and out["posts"] == []
    assert res["tasks"]["upload"][0] is True
