"""실행 일지(history_log) — 한 줄 추가·중복 방지·git 이력 복원."""
import json
import subprocess
from pathlib import Path

import pytest

import history_log
from history_log import append_history, backfill, history_path


def lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def status(**over) -> dict:
    base = {"id": "news", "name": "기사 수집", "ok": True, "summary": "신규 3건", "run_id": 11,
            "run_url": "https://github.com/Junjaee/ai-office/actions/runs/11", "request_id": "req-1",
            "trigger": "manual", "started_at": "2026-09-10T16:04:27+09:00", "duration_sec": 18,
            "updated_at": "2026-09-10T16:04:45+09:00", "counts": {"new": 3}, "log": ["x"], "tasks": []}
    base.update(over)
    return base


def test_history_path_uses_kst_month(tmp_path):
    assert history_path(tmp_path, "assembly", "news", "2026-09-30T23:30:00+09:00") == \
        tmp_path / "history" / "assembly" / "news" / "2026-09.jsonl"
    # UTC 로 적힌 시각도 KST 달로 (2026-09-30T15:30Z = KST 10월 1일 00:30)
    assert history_path(tmp_path, "assembly", "news", "2026-09-30T15:30:00Z").name == "2026-10.jsonl"


def test_append_writes_one_line_with_only_history_fields(tmp_path):
    path = append_history(tmp_path, "assembly", "news", status())
    assert path == tmp_path / "history" / "assembly" / "news" / "2026-09.jsonl"
    [line] = lines(path)
    assert line == {"automation": "news", "run_id": 11, "request_id": "req-1", "trigger": "manual",
                    "started_at": "2026-09-10T16:04:27+09:00", "duration_sec": 18, "ok": True,
                    "summary": "신규 3건", "url": "https://github.com/Junjaee/ai-office/actions/runs/11",
                    "recorded_at": "2026-09-10T16:04:45+09:00"}


def test_append_skips_same_run_twice(tmp_path):
    assert append_history(tmp_path, "assembly", "news", status()) is not None
    assert append_history(tmp_path, "assembly", "news", status(summary="다시")) is None
    assert len(lines(history_path(tmp_path, "assembly", "news", "2026-09-10T16:04:27+09:00"))) == 1


def test_local_run_without_run_id_is_kept_and_deduped_by_start(tmp_path):
    local = status(run_id=None, run_url=None, request_id=None, trigger="local")
    path = append_history(tmp_path, "assembly", "news", local)
    assert append_history(tmp_path, "assembly", "news", local) is None
    [line] = lines(path)
    assert line["trigger"] == "local" and "run_id" not in line and "url" not in line


def test_failure_is_recorded_too(tmp_path):
    path = append_history(tmp_path, "assembly", "news", status(run_id=12, ok=False, summary="뉴스 목록을 받아오지 못했어요"))
    assert lines(path)[0]["ok"] is False


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo_with_status_commits(tmp_path):
    r = tmp_path / "site"
    d = r / "public" / "status" / "assembly"
    d.mkdir(parents=True)
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.name", "t")
    git(r, "config", "user.email", "t@t")
    versions = [
        {"id": "news", "ok": True, "summary": "옛 형식(v1)", "updated_at": "2026-09-10T09:00:00+09:00"},
        status(run_id=21, summary="첫 실행"),
        status(run_id=22, summary="둘째 실행", started_at="2026-09-11T06:00:00+09:00", updated_at="2026-09-11T06:00:30+09:00"),
    ]
    for v in versions:
        (d / "news.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
        (d / "index.json").write_text('{"automations": ["news"]}', encoding="utf-8")
        git(r, "add", "-A")
        git(r, "commit", "-qm", "status")
    return r


def test_backfill_restores_every_status_commit_once(repo_with_status_commits):
    r = repo_with_status_commits
    assert backfill(r) == 3
    sept = lines(r / "history" / "assembly" / "news" / "2026-09.jsonl")
    assert [x.get("run_id") for x in sept] == [None, 21, 22]
    assert sept[0]["recorded_at"] == "2026-09-10T09:00:00+09:00" and sept[0]["summary"] == "옛 형식(v1)"
    assert backfill(r) == 0  # 두 번 돌려도 같은 결과
    assert len(lines(r / "history" / "assembly" / "news" / "2026-09.jsonl")) == 3


def test_cli_backfill(repo_with_status_commits, capsys):
    assert history_log.main(["--backfill", "--repo", str(repo_with_status_commits)]) == 0
    assert "3줄" in capsys.readouterr().out
