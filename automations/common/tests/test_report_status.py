import json
import subprocess
from pathlib import Path

import pytest

from report_status import report, write_status


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "site"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.name", "t")
    git(r, "config", "user.email", "t@t")
    (r / "public" / "status" / "assembly").mkdir(parents=True)
    (r / "public" / "status" / "assembly" / "index.json").write_text('{"automations": []}', encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "init")
    return r


def test_write_status_creates_file_and_updates_index(repo):
    path = write_status(repo, "minutes", {"id": "minutes", "name": "국회회의록 수집", "dept": "research",
                                          "ok": True, "summary": "신규 1건"})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["id"] == "minutes" and data["updated_at"].endswith("+09:00")
    index = json.loads((repo / "public" / "status" / "assembly" / "index.json").read_text(encoding="utf-8"))
    assert index["automations"] == ["minutes"]
    write_status(repo, "minutes", {"id": "minutes", "name": "x", "dept": "research", "ok": False, "summary": ""})
    index = json.loads((repo / "public" / "status" / "assembly" / "index.json").read_text(encoding="utf-8"))
    assert index["automations"] == ["minutes"]          # 중복 없음


def test_report_commits_and_survives_push_failure(repo, capsys):
    ok = report(repo, automation_id="minutes", name="국회회의록 수집", dept="research", ok=True,
                summary="신규 1건", counts={"new": 1}, next_run="매일 09:00", log_lines=["a", "b"], link="")
    assert ok is False                                   # 원격이 없어 push 실패
    assert "status: minutes" in git(repo, "log", "--oneline", "-1")
    assert "push 실패" in capsys.readouterr().err


def test_report_with_remote_pushes(repo, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "main")
    ok = report(repo, automation_id="minutes", name="국회회의록 수집", dept="research", ok=True,
                summary="신규 2건", counts={}, next_run="", log_lines=[], link="")
    assert ok is True
    assert "status: minutes" in subprocess.run(["git", "-C", str(bare), "log", "--oneline", "-1"],
                                                capture_output=True, text=True).stdout


def test_workspace_folder(repo):
    path = write_status(repo, "ledger", {"name": "지출 정산", "dept": "research", "ok": True, "summary": ""}, workspace="home")
    assert path == repo / "public" / "status" / "home" / "ledger.json"
    index = json.loads((repo / "public" / "status" / "home" / "index.json").read_text(encoding="utf-8"))
    assert index["automations"] == ["ledger"]
