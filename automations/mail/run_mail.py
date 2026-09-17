"""상임위 메일 자동화 — 재경위·예결위에서 온 새 메일을 텔레그램으로 알리고 지메일 라벨로 정리한다.

사용:
  python run_mail.py                  # 실제 실행 (알리고 라벨 정리, 상태 파일 커밋·push)
  python run_mail.py --dry-run        # 보내지도 라벨을 붙이지도 않고 찾은 것만 출력
  옵션: --config 경로 (기본: 이 파일 옆 config.actions.yaml)

check = 새 메일 확인(지메일), notify = 알림·정리(텔레그램 + 라벨).

**공개 저장소 주의**: 제목·보낸사람은 텔레그램으로만 보낸다. 커밋되는 상태 파일·실행 일지에는
위원회별 건수만 남긴다(mail_gmail.safe_lines) — 사용자 결정 2026-09-16.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# AI 오피스 공통 모듈 (automations/common): 오류 문구, 텔레그램, 상태 보고
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from errors import to_korean  # noqa: E402
from telegram_bot import send_message, telegram_env  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_gmail import (  # noqa: E402
    build_notice, build_query, ensure_label, file_message, gmail_service,
    message_meta, safe_lines, search_messages,
)
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:  # 보고 모듈이 없으면 보고 없이 동작
    report_status = None

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "mail"
AUTOMATION_NAME = "상임위 메일"
DEPT = "qa"
HERE = Path(__file__).resolve().parent
CHAT_KEY = "TELEGRAM_CHAT_ID_MAIL"        # 받는 사람이 주말 알림과 다르다
TOKEN_KEY = "NOTICE_530_BOT_TOKEN"        # 보내는 봇 = @notice_530_bot (530호 알림 공용).
                                          # 캘린더 봇(TELEGRAM_BOT_TOKEN)은 주말 일정 전송 전용 (사용자 결정 2026-09-17)


# ───────────────────────── 여기만 채운다 ─────────────────────────

def find_mails(service, rules: list[dict], days: int, limit: int, progress) -> list:
    """규칙마다 지메일을 찾아 아직 처리하지 않은 메일 목록(보낸 순)."""
    from googleapiclient.errors import HttpError

    found = []
    for rule in rules:
        label = (rule.get("label") or "").strip()
        if not label or not (rule.get("query") or "").strip():
            continue
        try:
            ids = search_messages(service, build_query(rule, days), limit)
            mails = [message_meta(service, mid) for mid in ids]
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", "?")
            raise RuntimeError(f"메일 읽기 실패: HTTP {status}") from None
        progress(f"{label} 새 메일 {len(mails)}건")
        found += [dataclasses.replace(m, label=label) for m in mails]
    return sorted(found, key=lambda m: m.ts)


def do_work(cfg: dict, args: argparse.Namespace, progress) -> dict:
    """새 메일 찾기 → 텔레그램 알림 → 라벨 붙이고 받은편지함에서 빼기."""
    from googleapiclient.errors import HttpError

    rules = list(cfg.get("committees") or [])
    days = int(cfg.get("lookback_days") or 7)
    limit = int(cfg.get("max_per_run") or 20)

    progress("지메일 확인")
    service = gmail_service()
    mails = find_mails(service, rules, days, limit, progress)
    lines = safe_lines(mails, rules)
    tasks = {"check": (True, f"새 메일 {len(mails)}건")}

    if not mails:
        tasks["notify"] = (True, "보낼 것 없음")
        # 5분마다 도는 자동화라, 새 메일이 없으면 상태 파일을 커밋하지 않는다
        # (커밋 288개/일 방지). 카드는 마지막으로 메일을 처리한 때를 계속 보여 준다.
        return {"counts": {"new": 0, "sent": 0}, "lines": lines, "tasks": tasks, "skip_report": True}

    notice = build_notice(mails)
    if args.dry_run:
        print("─── 보낼 글(시험 실행) ───")
        print(notice)
        tasks["notify"] = (True, "시험 실행 — 보내지 않음")
        return {"counts": {"new": len(mails), "sent": 0}, "lines": lines, "tasks": tasks}

    # 알림을 먼저 보내고 라벨을 붙인다 — 보내기에 실패하면 라벨이 안 붙어 다음 실행에서 다시 시도한다
    token, chat = telegram_env(CHAT_KEY, TOKEN_KEY)
    send_message(token, chat, notice, retries=int(cfg.get("retries") or 3),
                 timeout=int(cfg.get("timeout") or 30))
    progress(f"텔레그램 전송 {len(mails)}건")

    cache: dict = {}
    filed = 0
    for m in mails:
        try:
            file_message(service, m.id, ensure_label(service, m.label, cache))
            filed += 1
        except HttpError as exc:  # 한 통이 실패해도 나머지는 정리한다 (다음 실행에서 다시 알림)
            status = getattr(getattr(exc, "resp", None), "status", "?")
            progress(f"라벨 정리 실패 HTTP {status}")
    progress(f"라벨 정리 {filed}건")

    tasks["notify"] = (filed == len(mails), f"알림 {len(mails)}건, 정리 {filed}건")
    return {"counts": {"new": len(mails), "sent": 1, "failed": len(mails) - filed},
            "lines": lines, "tasks": tasks}


# ───────────────────────── 아래는 템플릿 그대로 ─────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="보내지도 라벨을 붙이지도 않고 시험 실행")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"), help="설정 파일 경로")
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_summary(counts: dict, elapsed_sec: float) -> str:
    """카드 부제 한 줄. counts 의 알려진 키를 한국어로 잇는다."""
    names = {"new": "새 메일", "replaced": "교체", "failed": "실패", "skip": "건너뜀",
             "sent": "알림", "updated": "갱신"}
    parts = [f"{names[k]} {v}건" for k, v in counts.items() if k in names]
    parts.append(f"{elapsed_sec / 60:.1f}분" if elapsed_sec >= 60 else f"{int(elapsed_sec)}초")
    return ", ".join(parts)


def build_tasks(cfg: dict, task_results: dict) -> list[dict]:
    """상태 JSON v2 의 tasks[]. 설정 `tasks:` 에 있는 id 만 만든다(원천은 app/workspaces/assembly.ts)."""
    out: list[dict] = []
    for tid in cfg.get("tasks") or []:
        ok, text = task_results.get(tid, (True, ""))
        out.append({"id": tid, "status": "done" if ok else "error", "summary": text})
    return out


def _report(cfg: dict, **kw) -> None:
    repo = (cfg.get("office_repo") or "").strip()
    if repo and report_status:
        report_status(repo, automation_id=AUTOMATION_ID, name=AUTOMATION_NAME, dept=DEPT,
                      next_run=cfg.get("next_run", ""), link=cfg.get("result_link", ""),
                      workspace=cfg.get("office_workspace", "assembly"), **kw)


def run(argv: list[str], work=None) -> int:
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
    if not args.dry_run and not result.get("skip_report"):
        _report(cfg, ok=ok, summary=summary, counts=counts, log_lines=[summary] + lines[:4],
                tasks=build_tasks(cfg, task_results), started_at=started_at,
                duration_sec=int(time.monotonic() - started))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
