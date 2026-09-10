"""__NAME__ 자동화.

사용:
  python run___ID__.py                       # 실제 실행 (끝나면 상태 파일 커밋·push)
  python run___ID__.py --dry-run             # 상태 파일을 쓰지 않는 시험 실행
  옵션: --config 경로 (기본: 이 파일 옆 config.actions.yaml)

채울 곳은 do_work() 하나다. 나머지(설정 읽기, 오류 → 한국어, 상태 보고)는 그대로 둔다.
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# AI 오피스 공통 모듈 (automations/common): 오류 문구, 상태 보고
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from errors import to_korean  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:  # 보고 모듈이 없으면 보고 없이 동작
    report_status = None

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "__ID__"
AUTOMATION_NAME = "__NAME__"
DEPT = "__DEPT__"
HERE = Path(__file__).resolve().parent


# ───────────────────────── 여기만 채운다 ─────────────────────────

def do_work(cfg: dict, args: argparse.Namespace, progress) -> dict:
    """실제 작업. 예외는 그대로 던진다(바깥에서 한국어 문구로 바꿔 보고한다).

    반환:
      {
        "counts": {"new": 3, "failed": 0, "total": 120},   # 화면 카드의 숫자. total 이 있으면 "누적 N건"
        "lines": ["[신규] …", "[실패] …"],                  # 카드 "자세히"에 보일 최근 기록 (앞 4줄만 쓰임)
        "tasks": {"collect": (True, "신규 3건")},           # 하위 작업 id → (성공 여부, 한 줄). id 는 config tasks: 와 같게
      }
    args.dry_run 이면 저장·전송은 하지 말고 목록·요약만 만든다.
    """
    progress("시작")
    raise NotImplementedError("do_work 를 구현하세요")


# ───────────────────────── 아래는 그대로 ─────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="상태 파일을 쓰지 않고 시험 실행")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"), help="설정 파일 경로")
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_summary(counts: dict, elapsed_sec: float) -> str:
    """카드 부제 한 줄. counts 의 알려진 키를 한국어로 잇는다."""
    names = {"new": "신규", "replaced": "교체", "failed": "실패", "skip": "건너뜀", "sent": "전송", "updated": "갱신"}
    parts = [f"{names[k]} {v}건" for k, v in counts.items() if k in names]
    parts.append(f"{elapsed_sec / 60:.1f}분" if elapsed_sec >= 60 else f"{int(elapsed_sec)}초")
    return ", ".join(parts)


def build_tasks(cfg: dict, task_results: dict) -> list[dict]:
    """상태 JSON v2 의 tasks[]. 설정 `tasks:` 에 있는 id 만 만든다(원천은 app/workspaces/<사무실>.ts)."""
    out: list[dict] = []
    for tid in cfg.get("tasks") or []:
        ok, text = task_results.get(tid, (True, ""))
        out.append({"id": tid, "status": "done" if ok else "error", "summary": text})
    return out


def _report(cfg: dict, **kw) -> None:
    """office_repo 가 설정돼 있고 보고 모듈이 있을 때만 상태 파일을 쓰고 push 한다."""
    repo = (cfg.get("office_repo") or "").strip()
    if repo and report_status:
        report_status(repo, automation_id=AUTOMATION_ID, name=AUTOMATION_NAME, dept=DEPT,
                      next_run=cfg.get("next_run", ""), link=cfg.get("result_link", ""),
                      workspace=cfg.get("office_workspace", "assembly"), **kw)


def run(argv: list[str], work=None) -> int:
    """실행. 실패해도 상태 파일에 한국어 원인을 남긴 뒤 1 을 돌려준다. dry-run 은 보고하지 않는다."""
    args = parse_args(argv)
    cfg = load_config(args.config)
    started_at = datetime.now(KST).isoformat(timespec="seconds")
    started = time.monotonic()
    work = work or do_work
    progress = lambda m: print(f"  · {m}")  # noqa: E731

    try:
        result = work(cfg, args, progress)
    except Exception as exc:  # noqa: BLE001 - 원인을 상태 파일에 남기고 실패로 끝낸다
        traceback.print_exc()
        summary = to_korean(exc)
        detail = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(f"{summary} ({detail})", file=sys.stderr)
        if not args.dry_run:
            _report(cfg, ok=False, summary=summary, log_lines=[summary, detail],
                    started_at=started_at, duration_sec=int(time.monotonic() - started))
        return 1

    counts = dict(result.get("counts") or {})
    lines = list(result.get("lines") or [])
    task_results = dict(result.get("tasks") or {})
    ok = counts.get("failed", 0) == 0 and all(v[0] for v in task_results.values())
    summary = build_summary(counts, time.monotonic() - started)
    print(summary)
    if not args.dry_run:
        _report(cfg, ok=ok, summary=summary, counts=counts, log_lines=[summary] + lines[:4],
                tasks=build_tasks(cfg, task_results), started_at=started_at,
                duration_sec=int(time.monotonic() - started))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
