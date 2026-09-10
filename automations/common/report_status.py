"""자동화 실행 결과를 AI 오피스 저장소의 상태 JSON으로 쓰고 git push 한다.

사용:
    from report_status import report
    report(REPO, automation_id="minutes", name="국회회의록 수집", dept="research", ok=True,
           summary="신규 3건", counts={"new": 3}, next_run="매일 09:00", log_lines=[...], link="")

push 실패는 자동화를 멈추지 않는다(경고만 출력, False 반환). 다음 실행 때 다시 push 된다.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
STATUS_DIR = Path("public") / "status"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=check)


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


def report(repo: str | Path, *, automation_id: str, name: str, dept: str, ok: bool, summary: str,
           counts: dict | None = None, next_run: str = "", log_lines: list[str] | None = None,
           link: str = "", running: bool = False, workspace: str = "assembly") -> bool:
    """상태 기록 → 커밋 → push. push까지 성공하면 True."""
    repo = Path(repo)
    if not (repo / ".git").exists():
        print(f"[report_status] 저장소가 없습니다: {repo}", file=sys.stderr)
        return False
    _git(repo, "pull", "--rebase", "-q", check=False)      # 원격이 없으면 조용히 실패
    write_status(repo, automation_id, {
        "name": name, "dept": dept, "ok": ok, "running": running, "summary": summary,
        "counts": counts or {}, "next_run": next_run, "log": (log_lines or [])[:5], "link": link,
    }, workspace=workspace)
    _git(repo, "add", str(STATUS_DIR))
    stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    commit = _git(repo, "commit", "-qm", f"status: {automation_id} {stamp}", check=False)
    if commit.returncode not in (0, 1):                     # 1 = 변경 없음
        print(f"[report_status] commit 실패: {commit.stderr.strip()}", file=sys.stderr)
        return False
    push = _git(repo, "push", "-q", check=False)
    if push.returncode != 0:
        print(f"[report_status] push 실패 (다음 실행 때 재시도): {push.stderr.strip()[:200]}", file=sys.stderr)
        return False
    return True
