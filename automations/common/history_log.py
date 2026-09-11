"""실행 일지(영구 기록): history/<ws>/<automation>/<YYYY-MM>.jsonl 에 실행 한 번 = 한 줄.

- append_history(): report() 가 상태 파일과 같은 커밋에 한 줄 더한다.
- backfill(): git 이력의 상태 파일(public/status/<ws>/<id>.json)에서 지난 실행을 복원한다.
    python automations/common/history_log.py --backfill
자동화마다 파일을 따로 두어 동시에 끝나도 서로 덮어쓰지 않는다(설계 3.3).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
HISTORY_DIR = Path("history")
STATUS_DIR = Path("public") / "status"
# 상태 파일에서 일지로 옮기는 필드 (run_url 은 url 로)
FIELDS = ("run_id", "request_id", "trigger", "started_at", "duration_sec", "ok", "summary")


def _kst(iso: str) -> datetime:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return datetime.now(KST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST)


def history_path(repo: str | Path, workspace: str, automation_id: str, when: str) -> Path:
    """when(ISO)의 KST 달 파일."""
    return Path(repo) / HISTORY_DIR / workspace / automation_id / f"{_kst(when).strftime('%Y-%m')}.jsonl"


def history_line(automation_id: str, status: dict, recorded_at: str) -> dict:
    """상태 파일 내용 → 일지 한 줄. 값이 없는 필드는 넣지 않는다."""
    line: dict = {"automation": automation_id}
    for k in FIELDS:
        v = status.get(k)
        if v is not None and v != "":
            line[k] = v
    if status.get("run_url"):
        line["url"] = status["run_url"]
    line["recorded_at"] = recorded_at
    return line


def _key(line: dict) -> str:
    """같은 실행 판별: run_id, 없으면(이 PC 실행·옛 형식) 시작 시각 또는 기록 시각."""
    rid = line.get("run_id")
    return f"run:{rid}" if rid is not None else f"at:{line.get('started_at') or line.get('recorded_at') or ''}"


def _existing_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            try:
                keys.add(_key(json.loads(raw)))
            except (json.JSONDecodeError, AttributeError):
                continue
    return keys


def append_history(repo: str | Path, workspace: str, automation_id: str, status: dict,
                   recorded_at: str | None = None) -> Path | None:
    """한 줄 추가하고 파일 경로를 돌려준다. 같은 실행이 이미 있으면 쓰지 않고 None."""
    recorded_at = recorded_at or status.get("updated_at") or datetime.now(KST).isoformat(timespec="seconds")
    line = history_line(automation_id, status, recorded_at)
    path = history_path(repo, workspace, automation_id, line.get("started_at") or recorded_at)
    if _key(line) in _existing_keys(path):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout


def backfill(repo: str | Path) -> int:
    """git 이력의 상태 파일 커밋마다 한 줄. 이미 있는 실행은 건너뛴다. 새로 쓴 줄 수."""
    repo = Path(repo)
    base = repo / STATUS_DIR
    if not base.exists():
        return 0
    added = 0
    for ws_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for f in sorted(ws_dir.glob("*.json")):
            if f.name == "index.json":
                continue
            rel = f.relative_to(repo).as_posix()
            for sha in _git(repo, "log", "--reverse", "--format=%H", "--", rel).split():
                try:
                    data = json.loads(_git(repo, "show", f"{sha}:{rel}"))
                except (subprocess.CalledProcessError, json.JSONDecodeError):
                    continue
                if append_history(repo, ws_dir.name, f.stem, data):
                    added += 1
    return added


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="실행 일지 도구")
    p.add_argument("--backfill", action="store_true", help="git 이력의 상태 파일에서 지난 실행을 일지로 복원")
    p.add_argument("--repo", default=str(Path(__file__).resolve().parents[2]), help="저장소 폴더 (기본: 이 저장소)")
    args = p.parse_args(argv)
    if not args.backfill:
        p.print_help()
        return 2
    print(f"일지에 {backfill(args.repo)}줄 복원")
    return 0


if __name__ == "__main__":
    sys.exit(main())
