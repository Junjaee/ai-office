"""자동화 실행 결과를 AI 오피스 저장소의 상태 JSON(v2)으로 쓰고 git push 한다.

사용:
    from report_status import report
    report(REPO, automation_id="minutes", name="국회회의록 수집", dept="research", ok=True,
           summary="신규 3건", counts={"new": 3}, next_run="매일 09:00", log_lines=[...], link="",
           tasks=[{"id": "collect", "status": "done", "summary": "신규 3건"}],
           started_at="2026-09-11T09:01:20+09:00", duration_sec=112)

v2 추가 필드 (설계 문서 3.6절):
  run_id / run_url / request_id / trigger 는 환경변수에서 자동으로 채운다
  (GITHUB_RUN_ID, GITHUB_SERVER_URL + GITHUB_REPOSITORY, REQUEST_ID, GITHUB_EVENT_NAME).
  값이 없는 필드는 JSON에 넣지 않는다(구버전 파일과 호환). running 은 항상 false.

push 실패는 자동화를 멈추지 않는다: pull --rebase 후 최대 3회 재시도, 전부 실패하면 경고만 출력하고
False 반환. 다음 실행 때 다시 push 된다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from history_log import HISTORY_DIR, append_history

KST = timezone(timedelta(hours=9))
STATUS_DIR = Path("public") / "status"
PUSH_ATTEMPTS = 3
_TRIGGERS = {"workflow_dispatch": "manual", "schedule": "schedule"}


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


def run_meta() -> dict:
    """환경변수에서 run_id / run_url / request_id / trigger 를 읽는다. 없는 값은 키를 만들지 않는다."""
    out: dict = {}
    run_id = (os.environ.get("GITHUB_RUN_ID") or "").strip()
    if run_id.isdigit():
        out["run_id"] = int(run_id)
        server = (os.environ.get("GITHUB_SERVER_URL") or "").strip().rstrip("/")
        repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip().strip("/")
        if server and repo:
            out["run_url"] = f"{server}/{repo}/actions/runs/{run_id}"
    request_id = (os.environ.get("REQUEST_ID") or "").strip()
    if request_id:
        out["request_id"] = request_id
    event = (os.environ.get("GITHUB_EVENT_NAME") or "").strip()
    # 예약은 Cloudflare 시계가 workflow_dispatch 로 깨우므로 event 만 보면 수동과 구분되지 않는다.
    # 요청 번호가 cron- 으로 시작하면 예약으로 남긴다 (worker/schedule.ts 의 cronRequestId, 2026-09-17)
    if request_id.startswith("cron-"):
        out["trigger"] = "schedule"
    else:
        out["trigger"] = _TRIGGERS.get(event, "local")
    return out


def write_status(repo: Path, automation_id: str, data: dict, workspace: str = "assembly") -> Path:
    """상태 파일과 index.json을 사무실(workspace) 폴더에 쓴다. updated_at은 항상 지금(KST)으로 채운다."""
    d = repo / STATUS_DIR / workspace
    d.mkdir(parents=True, exist_ok=True)
    payload = {**data, "id": automation_id, "updated_at": datetime.now(KST).isoformat(timespec="seconds")}
    path = d / f"{automation_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    index_path = d / "index.json"
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        index = {"automations": []}
    ids = [x for x in index.get("automations", []) if x != automation_id] + [automation_id]
    index_path.write_text(json.dumps({"automations": sorted(ids), "generated_at": payload["updated_at"]},
                                     ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_payload(*, name: str, dept: str, ok: bool, summary: str, counts: dict | None, next_run: str,
                  log_lines: list[str] | None, link: str, tasks: list[dict] | None, started_at: str,
                  duration_sec: int | None) -> dict:
    """v1 필드 + v2 필드. v2 값이 None/빈 문자열이면 키를 넣지 않는다."""
    data = {
        "name": name, "dept": dept, "ok": ok, "running": False, "summary": summary,
        "counts": counts or {}, "next_run": next_run, "log": (log_lines or [])[:5], "link": link,
    }
    data.update(run_meta())
    if started_at:
        data["started_at"] = started_at
    if duration_sec is not None:
        data["duration_sec"] = int(duration_sec)
    if tasks is not None:
        data["tasks"] = [dict(t) for t in tasks]
    return data


def _push_with_retry(repo: Path) -> bool:
    for attempt in range(1, PUSH_ATTEMPTS + 1):
        push = _git(repo, "push", "-q", check=False)
        if push.returncode == 0:
            return True
        print(f"[report_status] push 실패 ({attempt}/{PUSH_ATTEMPTS}): {push.stderr.strip()[:200]}", file=sys.stderr)
        if attempt == PUSH_ATTEMPTS:
            break
        # 다른 자동화가 먼저 push 했을 수 있다 → 원격을 받아 위에 얹고 다시 시도.
        # 충돌(-X theirs = rebase 중인 우리 커밋 우선)이 그래도 나면 rebase를 되돌리고 다음 시도로.
        pull = _git(repo, "pull", "--rebase", "-X", "theirs", "-q", check=False)
        if pull.returncode != 0:
            print(f"[report_status] pull --rebase 실패: {pull.stderr.strip()[:200]}", file=sys.stderr)
            _git(repo, "rebase", "--abort", check=False)
    print("[report_status] push를 포기합니다 (다음 실행 때 재시도)", file=sys.stderr)
    return False


def report(repo: str | Path, *, automation_id: str, name: str, dept: str, ok: bool, summary: str,
           counts: dict | None = None, next_run: str = "", log_lines: list[str] | None = None,
           link: str = "", running: bool = False, workspace: str = "assembly",
           tasks: list[dict] | None = None, started_at: str = "", duration_sec: int | None = None) -> bool:
    """상태 기록 → 커밋 → push(최대 3회). push까지 성공하면 True.

    `running` 인자는 구버전 호출과의 호환을 위해 남겨 두지만 무시한다(파일에는 항상 false).
    """
    repo = Path(repo)
    if not (repo / ".git").exists():
        print(f"[report_status] 저장소가 없습니다: {repo}", file=sys.stderr)
        return False
    _git(repo, "pull", "--rebase", "-q", check=False)      # 원격이 없으면 조용히 실패
    path = write_status(repo, automation_id, build_payload(
        name=name, dept=dept, ok=ok, summary=summary, counts=counts, next_run=next_run, log_lines=log_lines,
        link=link, tasks=tasks, started_at=started_at, duration_sec=duration_sec,
    ), workspace=workspace)
    # 영구 일지: 상태 파일과 같은 커밋에 한 줄 (자동화별 파일이라 동시에 끝나도 안 겹친다)
    append_history(repo, workspace, automation_id, json.loads(path.read_text(encoding="utf-8")))
    _git(repo, "add", str(STATUS_DIR), str(HISTORY_DIR))
    stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    commit = _git(repo, "commit", "-qm", f"status: {automation_id} {stamp}", check=False)
    if commit.returncode not in (0, 1):                     # 1 = 변경 없음
        print(f"[report_status] commit 실패: {commit.stderr.strip()}", file=sys.stderr)
        return False
    return _push_with_retry(repo)
