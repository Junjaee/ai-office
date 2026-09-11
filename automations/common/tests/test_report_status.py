import json
import subprocess
from pathlib import Path

import pytest

import report_status
from report_status import build_payload, report, run_meta, write_status

GITHUB_VARS = ("GITHUB_RUN_ID", "GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "REQUEST_ID", "GITHUB_EVENT_NAME")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """이 테스트 자체가 GitHub Actions 안에서 돌아도 결과가 같도록 환경변수를 비운다."""
    for k in GITHUB_VARS:
        monkeypatch.delenv(k, raising=False)


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


@pytest.fixture
def remote(repo, tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    git(repo, "remote", "add", "origin", str(bare))
    git(repo, "push", "-q", "-u", "origin", "main")
    return bare


def read_status(repo: Path, automation_id: str = "minutes", workspace: str = "assembly") -> dict:
    return json.loads((repo / "public" / "status" / workspace / f"{automation_id}.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 기존 동작 (v1)

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


def test_report_with_remote_pushes(repo, remote):
    ok = report(repo, automation_id="minutes", name="국회회의록 수집", dept="research", ok=True,
                summary="신규 2건", counts={}, next_run="", log_lines=[], link="")
    assert ok is True
    assert "status: minutes" in subprocess.run(["git", "-C", str(remote), "log", "--oneline", "-1"],
                                                capture_output=True, text=True).stdout


def test_workspace_folder(repo):
    path = write_status(repo, "ledger", {"name": "지출 정산", "dept": "research", "ok": True, "summary": ""}, workspace="home")
    assert path == repo / "public" / "status" / "home" / "ledger.json"
    index = json.loads((repo / "public" / "status" / "home" / "index.json").read_text(encoding="utf-8"))
    assert index["automations"] == ["ledger"]


# ---------------------------------------------------------------- v2 필드

def test_v2_fields_serialized(repo):
    tasks = [{"id": "collect", "status": "done", "summary": "신규 3건"},
             {"id": "replace", "status": "done", "summary": "교체 1건"}]
    report(repo, automation_id="minutes", name="국회회의록 수집", dept="research", ok=True, summary="s",
           counts={"new": 3, "replaced": 1, "failed": 0, "total": 5898}, next_run="매일 09:00",
           log_lines=["s"], link="https://drive/x", workspace="assembly",
           tasks=tasks, started_at="2026-09-11T09:01:20+09:00", duration_sec=112)
    data = read_status(repo)
    assert data["tasks"] == tasks
    assert data["started_at"] == "2026-09-11T09:01:20+09:00"
    assert data["duration_sec"] == 112
    assert data["trigger"] == "local"
    # v1 필드는 그대로
    assert data["id"] == "minutes" and data["ok"] is True and data["counts"]["total"] == 5898
    assert data["link"] == "https://drive/x" and data["next_run"] == "매일 09:00"


def test_env_maps_to_run_id_url_request_trigger(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "17234567890")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Junjaee/ai-office")
    monkeypatch.setenv("REQUEST_ID", "req-20260911090001-a1b2")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    meta = run_meta()
    assert meta == {
        "run_id": 17234567890,
        "run_url": "https://github.com/Junjaee/ai-office/actions/runs/17234567890",
        "request_id": "req-20260911090001-a1b2",
        "trigger": "manual",
    }
    assert isinstance(meta["run_id"], int)


def test_env_schedule_trigger_without_request_id(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "5")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("REQUEST_ID", "")                 # 예약 실행: 입력이 비어 있음
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    meta = run_meta()
    assert meta["trigger"] == "schedule" and "request_id" not in meta
    assert meta["run_url"] == "https://github.com/o/r/actions/runs/5"


def test_none_and_empty_fields_are_omitted(repo):
    """로컬 실행: 환경변수 없음, v2 인자 생략 → 구버전과 같은 키 + trigger=local 만."""
    report(repo, automation_id="minutes", name="n", dept="research", ok=True, summary="s")
    data = read_status(repo)
    for key in ("run_id", "run_url", "request_id", "started_at", "duration_sec", "tasks"):
        assert key not in data
    assert data["trigger"] == "local"
    # run_id만 있고 서버/저장소 정보가 없으면 run_url도 생략
    payload = build_payload(name="n", dept="d", ok=True, summary="", counts=None, next_run="", log_lines=None,
                            link="", tasks=None, started_at="", duration_sec=None)
    assert "run_url" not in payload and "run_id" not in payload


def test_run_id_without_server_url_omits_run_url(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "42")
    meta = run_meta()
    assert meta["run_id"] == 42 and "run_url" not in meta


def test_running_is_always_false(repo):
    report(repo, automation_id="minutes", name="n", dept="research", ok=True, summary="s", running=True)
    assert read_status(repo)["running"] is False


def test_tasks_empty_list_is_kept(repo):
    """tasks=[]는 '하위 작업 없음'이라는 뜻이므로 None과 달리 파일에 남긴다."""
    report(repo, automation_id="minutes", name="n", dept="research", ok=True, summary="s", tasks=[])
    assert read_status(repo)["tasks"] == []


# ---------------------------------------------------------------- push 재시도

def test_push_retries_after_rejection(repo, remote, tmp_path, monkeypatch, capsys):
    """첫 push 직전에 다른 클론이 원격에 커밋을 넣어 거부되게 만든 뒤, pull --rebase 재시도로 성공해야 한다."""
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True)
    git(other, "config", "user.name", "o")
    git(other, "config", "user.email", "o@o")

    real_git = report_status._git
    pushes: list[int] = []

    def racing_git(r, *args, **kw):
        if args and args[0] == "push":
            pushes.append(1)
            if len(pushes) == 1:                         # 첫 push 직전에 남이 먼저 push
                (other / "public" / "status" / "assembly" / "ledger.json").write_text('{"id": "ledger"}', encoding="utf-8")
                git(other, "add", "-A")
                git(other, "commit", "-qm", "status: ledger")
                git(other, "push", "-q")
        return real_git(r, *args, **kw)

    monkeypatch.setattr(report_status, "_git", racing_git)
    ok = report(repo, automation_id="minutes", name="n", dept="research", ok=True, summary="s")
    assert ok is True
    assert len(pushes) == 2                              # 거부 1회 + 성공 1회
    assert "push 실패 (1/3)" in capsys.readouterr().err
    remote_log = subprocess.run(["git", "-C", str(remote), "log", "--oneline", "-2"],
                                capture_output=True, text=True).stdout
    assert "status: minutes" in remote_log and "status: ledger" in remote_log
    # rebase 뒤에도 우리 파일과 남의 파일이 모두 남아 있다
    assert (repo / "public" / "status" / "assembly" / "ledger.json").exists()
    assert read_status(repo)["id"] == "minutes"


def test_push_gives_up_after_three_attempts(repo, remote, monkeypatch, capsys):
    real_git = report_status._git
    pushes: list[int] = []

    def failing_git(r, *args, **kw):
        if args and args[0] == "push":
            pushes.append(1)
            return subprocess.CompletedProcess(args, 1, "", "rejected")
        return real_git(r, *args, **kw)

    monkeypatch.setattr(report_status, "_git", failing_git)
    ok = report(repo, automation_id="minutes", name="n", dept="research", ok=True, summary="s")
    assert ok is False and len(pushes) == 3
    err = capsys.readouterr().err
    assert "push 실패 (3/3)" in err and "포기" in err
    assert "status: minutes" in git(repo, "log", "--oneline", "-1")    # 커밋은 남는다


# ---------------------------------------------------------------- 실행 일지

def test_report_appends_history_line_in_same_commit(repo, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "555")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "Junjaee/ai-office")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "schedule")
    report(repo, automation_id="minutes", name="국회회의록 수집", dept="research", ok=True, summary="신규 1건",
           started_at="2026-09-11T09:00:00+09:00", duration_sec=60)
    changed = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert "history/assembly/minutes/2026-09.jsonl" in changed
    assert "public/status/assembly/minutes.json" in changed
    line = json.loads((repo / "history" / "assembly" / "minutes" / "2026-09.jsonl").read_text(encoding="utf-8").strip())
    assert line["run_id"] == 555 and line["trigger"] == "schedule" and line["summary"] == "신규 1건"
    assert git(repo, "status", "--porcelain") == ""
