"""주식 신호 자동화 — 매일 아침 시장 상태 한 통, 분기가 바뀐 첫 실행에는 가치+주주환원 상위 20종목 한 통.

사용:
  python run_stock.py                       # 실제 실행 (보내고 상태 파일 커밋·push)
  python run_stock.py --dry-run             # 보내지 않고 보낼 글만 출력 (상태 파일도 안 씀)
  python run_stock.py --dry-run --screen    # 분기 알림을 강제로 만들어 본다 (SEC 묶음 1.4GB 필요)
  python run_stock.py --dry-run --facts 경로 # 이미 받아 둔 companyfacts.zip 을 쓴다
  python run_stock.py --find-chat --dry-run # 봇에게 말을 건 대화방 번호 출력 (TELEGRAM_CHAT_ID_STOCK 정할 때)
  옵션: --config 경로 (기본: 이 파일 옆 config.actions.yaml)

quotes = 구성종목·시세(·재무) 받기, scan = 시장 상태·점수, notify = 텔레그램.
설계: docs/superpowers/specs/2026-09-22-주식-신호-자동화-design.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

# AI 오피스 공통 모듈 (automations/common): 오류 문구, 상태 보고
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from errors import to_korean  # noqa: E402
from telegram_bot import list_chats, send_message, telegram_env  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stock_data as D  # noqa: E402
import stock_fund as F  # noqa: E402
import stock_message as M  # noqa: E402
import stock_score as S  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:  # 보고 모듈이 없으면 보고 없이 동작
    report_status = None

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "stock"
AUTOMATION_NAME = "주식 신호"
DEPT = "finance"
HERE = Path(__file__).resolve().parent
TOKEN_KEY, CHAT_KEY = "TELEGRAM_BOT_TOKEN_JUNJAE_BOT", "TELEGRAM_CHAT_ID_STOCK"


# ───────────────────────── 여기만 채운다 ─────────────────────────

def load_local_secrets(cfg: dict) -> None:
    """이 PC 에서 시험할 때: 개인 폴더의 config.yaml(gitignore) 값을 환경변수로. 값은 어디에도 찍지 않는다."""
    p = Path(cfg.get("local_secrets") or "")
    if not p.is_absolute():
        p = HERE.parent.parent / p
    if not cfg.get("local_secrets") or not p.exists():
        return
    try:
        sec = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return
    for env_key, file_key in ((TOKEN_KEY, "telegram_bot_token"), (CHAT_KEY, "telegram_chat_id")):
        if not os.environ.get(env_key) and sec.get(file_key):
            os.environ[env_key] = str(sec[file_key]).strip()


def find_chats(progress) -> dict:
    token = (os.environ.get(TOKEN_KEY) or "").strip()
    if not token:
        raise RuntimeError(f"텔레그램 설정 없음: {TOKEN_KEY}")
    progress("봇에게 말을 건 대화방 찾는 중")
    chats = list_chats(token)
    if not chats:
        print("봇에게 말을 건 대화방이 없습니다. 봇에게 아무 메시지나 보낸 뒤 다시 실행하세요.")
    for c in chats:
        print(f"대화방 번호 {c['id']} · {c['type']} · {c['name']}" + (f" (@{c['username']})" if c["username"] else ""))
    return {"counts": {}, "lines": [], "tasks": {}}


def previous_state(cfg: dict) -> dict:
    """지난 실행의 상태 파일에서 기준일·마지막 분기 알림을 읽는다(같은 날 중복 발송 방지, 분기 판정)."""
    p = HERE.parent.parent / "public" / "status" / cfg.get("office_workspace", "home") / f"{AUTOMATION_ID}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"date": None, "quarter": None}
    return M.parse_state_lines(data.get("log_lines") or [])


def observe_mode(cfg: dict, today: date) -> bool:
    until = cfg.get("observe_until")
    return bool(until) and today <= date.fromisoformat(str(until))


def do_work(cfg: dict, args: argparse.Namespace, progress) -> dict:
    """시세로 시장 상태를 만들고, 분기 첫 실행이면 재무값으로 상위 종목을 뽑아 텔레그램으로 보낸다."""
    load_local_secrets(cfg)
    if getattr(args, "find_chat", False):
        return find_chats(progress)

    today = datetime.now(KST).date()
    prev = previous_state(cfg)
    observe = observe_mode(cfg, today)
    sec_ua = cfg.get("sec_user_agent") or "ai-office stock automation ai-office-bot@users.noreply.github.com"

    # quotes ─ 구성종목·시세
    progress("S&P 500 구성종목 받는 중")
    mem = D.members()
    progress(f"시세 받는 중 ({len(mem)}종목)")
    close, failed = D.prices(list(mem["ticker"]), period=cfg.get("price_period", "18mo"))
    fail_rate = len([t for t in failed if t in set(mem["ticker"])]) / max(len(mem), 1)
    if fail_rate > float(cfg.get("max_fail_rate", 0.05)):
        raise RuntimeError(f"시세 수집 실패: {len(failed)}종목({fail_rate:.0%}) 을 받지 못함")
    state = S.market_state(close)
    asof: date = state["date"]
    if prev["date"] == asof.isoformat() and not args.dry_run and not getattr(args, "screen", False):
        progress(f"미국 {asof} 기준 알림은 이미 보냄 — 쉬는 날이거나 중복 실행")
        return {"counts": {"skip": 1}, "lines": M.public_lines(state, 0, False, None, 0, len(failed)),
                "tasks": {"quotes": (True, f"{len(mem) - len(failed)}종목, 새 자료 없음"),
                          "scan": (True, "건너뜀"), "notify": (True, "이미 보냄")}}

    # scan ─ 분기 첫 실행이면 재무제표까지
    do_screen = (getattr(args, "screen", False) or S.is_new_quarter(prev["quarter"], today)) \
        and not getattr(args, "no_screen", False)
    picks, table, new, gone, quarter = None, None, [], [], S.quarter_of(today)
    if do_screen:
        ciks = D.cik_map(mem, sec_ua)
        facts_path = getattr(args, "facts", None) or cfg.get("facts_cache") or str(Path(tempfile.gettempdir()) / "companyfacts.zip")
        progress("SEC 재무 묶음 확인 중 (없으면 약 1.4GB 내려받음)")
        facts_path = D.download_facts(facts_path, sec_ua, progress)
        progress(f"재무제표 해석 중 ({len(ciks)}개 회사)")
        fund = F.read_zip(facts_path, ciks, asof, progress)
        last_close = close.reindex(columns=list(mem["ticker"])).ffill().iloc[-1]
        table = S.score_table(mem, last_close, fund)
        if len(table) < int(cfg.get("min_candidates", 300)):
            raise RuntimeError(f"재무 자료 부족: 점수를 매길 수 있는 종목이 {len(table)}개뿐")
        picks = S.top_n(table, int(cfg.get("top_n", 20)), cfg.get("weight", "equal"), close)
        new, gone = S.diff_picks(list(picks["ticker"]), None)   # v1: 지난 목록 없음(공개 저장소에 종목명 금지)
        progress(f"점수 계산 완료: 후보 {len(table)}, 상위 {len(picks)}")

    # notify
    note = f"오늘 {quarter} 분기 종목 알림도 보냅니다." if do_screen else ""
    text1 = M.status_text(state, observe, note)
    text2 = M.screen_text(picks, quarter, cfg.get("weight", "equal"), observe, new, gone, len(table), asof) if do_screen else ""
    if args.dry_run:
        print("----- 보낼 글 (시험 실행: 보내지 않음) -----")
        print(text1)
        if text2:
            print()
            print(text2)
        print("--------------------------------------------")
        sent = "시험 실행 — 보내지 않음"
    else:
        token, chat = telegram_env(CHAT_KEY, TOKEN_KEY)
        send_message(token, chat, text1, retries=int(cfg.get("retries", 3)), timeout=int(cfg.get("timeout", 30)))
        if text2:
            send_message(token, chat, text2, retries=int(cfg.get("retries", 3)), timeout=int(cfg.get("timeout", 30)))
        sent = "상태 1통" + (" + 분기 종목 1통" if text2 else "")
        progress("텔레그램 전송 완료")

    n_cand = len(table) if table is not None else 0
    return {
        "counts": {"sent": 0 if args.dry_run else (2 if text2 else 1), "failed": 0},
        "lines": M.public_lines(state, n_cand, do_screen, quarter if do_screen else None, len(new), len(failed)),
        "tasks": {
            "quotes": (True, f"{len(mem) - len(failed)}종목 시세" + (f", 재무 {n_cand}" if do_screen else "")),
            "scan": (True, f"SPY 200일선 {'위' if state['spy_above_ma200'] else '아래'} · VIX {state['vix']:.0f}"
                     + (f" · 분기 상위 {len(picks)}" if do_screen else "")),
            "notify": (True, sent),
        },
    }


# ───────────────────────── 아래는 그대로 ─────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="보내지 않고 상태 파일도 쓰지 않는 시험 실행")
    p.add_argument("--screen", action="store_true", help="분기 종목 알림을 강제로 만든다")
    p.add_argument("--no-screen", action="store_true", help="분기 종목 알림을 만들지 않는다 (시장 상태만)")
    p.add_argument("--facts", default="", help="이미 받아 둔 companyfacts.zip 경로")
    p.add_argument("--find-chat", action="store_true", help="봇에게 말을 건 대화방 번호 출력 (보내지 않음)")
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
