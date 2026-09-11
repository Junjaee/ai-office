"""주말 일정 알림 — 매주 목요일, 530호 일정(비공개) 캘린더의 이번 주 토·일 일정을 텔레그램으로 보낸다.

사용:
  python run_weekend.py                       # 실제 실행 (보내고 상태 파일 커밋·push)
  python run_weekend.py --dry-run             # 보내지 않고 보낼 글만 출력 (상태 파일도 안 씀)
  python run_weekend.py --find-chat --dry-run # 봇에게 '시작'을 누른 대화방 번호 출력 (TELEGRAM_CHAT_ID 정할 때)
  옵션: --config 경로 (기본: 이 파일 옆 config.actions.yaml)

fetch = 주말 일정 모으기(캘린더), send = 텔레그램 보내기.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

# AI 오피스 공통 모듈 (automations/common): 오류 문구, 상태 보고
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from errors import to_korean  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from weekend_calendar import build_message, calendar_service, fetch_events, to_events, upcoming_weekend  # noqa: E402
from weekend_telegram import list_chats, send_message, telegram_env  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:  # 보고 모듈이 없으면 보고 없이 동작
    report_status = None

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "weekend"
AUTOMATION_NAME = "주말 일정 알림"
DEPT = "partner"
HERE = Path(__file__).resolve().parent


# ───────────────────────── 여기만 채운다 ─────────────────────────

def today_kst() -> date:
    return datetime.now(KST).date()


def find_chats(progress) -> dict:
    """봇에게 '시작'을 누른 대화방 번호를 실행 기록에 찍는다 (TELEGRAM_CHAT_ID 를 정할 때)."""
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("텔레그램 설정 없음: TELEGRAM_BOT_TOKEN")
    progress("봇에게 말을 건 대화방 찾는 중")
    chats = list_chats(token)
    if not chats:
        print("봇에게 말을 건 대화방이 없습니다. 받는 분이 봇 링크에서 '시작'을 누른 뒤 다시 실행하세요.")
    for c in chats:
        print(f"대화방 번호 {c['id']} · {c['type']} · {c['name']}" + (f" (@{c['username']})" if c["username"] else ""))
    return {"counts": {}, "lines": [], "tasks": {}}


def do_work(cfg: dict, args: argparse.Namespace, progress) -> dict:
    """이번 주 토·일 일정을 캘린더에서 읽어(fetch) 받는 분 텔레그램으로 보낸다(send). 예외는 그대로 던진다."""
    if getattr(args, "find_chat", False):
        return find_chats(progress)

    days = upcoming_weekend(today_kst())
    progress(f"{days[0]} ~ {days[1]} 일정 읽는 중")
    try:
        items = fetch_events(calendar_service(), cfg["calendar_id"], days)
    except Exception as exc:  # googleapiclient 의 HttpError — 권한 없음(403)·캘린더 없음(404) 등
        if type(exc).__name__ != "HttpError":
            raise
        status = getattr(getattr(exc, "resp", None), "status", "?")
        raise RuntimeError(f"캘린더 읽기 실패: HTTP {status}") from None
    events = to_events(items, days)
    text = build_message(cfg.get("calendar_name") or "캘린더", days, events)
    per_day = " · ".join(f"{'토' if d.weekday() == 5 else '일'} {sum(1 for e in events if e.day == d)}건" for d in days)

    if args.dry_run:
        print("----- 보낼 글 (시험 실행: 보내지 않음) -----")
        print(text)
        print("--------------------------------------------")
        sent_note = "시험 실행 — 보내지 않음"
    else:
        token, chat = telegram_env()
        send_message(token, chat, text, retries=int(cfg.get("retries", 3)), timeout=int(cfg.get("timeout", 30)))
        sent_note = "받는 분에게 보냄"
        progress("텔레그램 전송 완료")
    return {
        "counts": {"events": len(events), "sent": 0 if args.dry_run else 1},
        "lines": [f"[{e.day.month}/{e.day.day}] {e.title}" for e in events[:6]],
        "tasks": {"fetch": (True, per_day), "send": (True, sent_note)},
    }


# ───────────────────────── 아래는 그대로 ─────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="보내지 않고 상태 파일도 쓰지 않는 시험 실행")
    p.add_argument("--find-chat", action="store_true", help="봇에게 '시작'을 누른 대화방 번호 출력 (보내지 않음)")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"), help="설정 파일 경로")
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_summary(counts: dict, elapsed_sec: float) -> str:
    """카드 부제 한 줄. counts 의 알려진 키를 한국어로 잇는다."""
    names = {"events": "주말 일정", "new": "신규", "replaced": "교체", "failed": "실패", "skip": "건너뜀", "sent": "전송", "updated": "갱신"}
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
