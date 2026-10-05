"""주식 분석 자동화 — 미국 종목 시세·재무를 받아 점검표를 계산하고 사이트 저장 공간에 올린다.

사용:
  python run_analyst.py                      # 실제 실행 (끝나면 상태 파일 커밋·push)
  python run_analyst.py --dry-run            # 받아서 계산만 하고 보내지 않는다
  옵션: --config 경로, --market us

네 관점(싸고 탄탄·실적 개선·사건·돈 몰림) 판정과 미국 공시(EDGAR 8-K) 분류를 더해 발굴 판과 관점 기록도 올린다.
AI 를 부르지 않는다. 저장소가 공개라서 상태 파일·로그에는 건수만 남기고 종목 기호·이름은 적지 않는다
(자료는 Worker /api/stock/ingest → R2 에만 둔다. 설계서 §4.5).
"""
from __future__ import annotations

import argparse
import contextlib
import io
import logging
import os
import sys
import time
import traceback
import warnings
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from errors import to_korean  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:
    report_status = None

from analyst_checks import LENS_LABEL, LENS_ORDER, board_row, diag, lens_info, lenses, load_rules, medians, peers, ref_for, run_checks  # noqa: E402
from analyst_events import classify  # noqa: E402
from analyst_metrics import build_record  # noqa: E402
from analyst_publish import Site  # noqa: E402
from analyst_sources_edgar import Edgar  # noqa: E402
from analyst_sources_us import fetch_raw  # noqa: E402

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "analyst"
AUTOMATION_NAME = "주식 분석"
DEPT = "finance"
HERE = Path(__file__).resolve().parent

# yfinance 는 받지 못한 종목의 기호를 직접 로그에 찍는다 — 공개 저장소의 Actions 로그에 남지 않게 막는다
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("yfinance").propagate = False


def read_universe(path: str | Path) -> list[str]:
    out = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        t = line.split("#", 1)[0].strip().upper()
        if t and t not in out:
            out.append(t)
    return out


def do_work(cfg: dict, args: argparse.Namespace, progress, fetch=fetch_raw, site: Site | None = None, filings_for=None, clock=time.monotonic) -> dict:
    market = getattr(args, "market", "us") or "us"
    if site is None:
        site = Site(cfg["site_url"], token=os.environ.get("LIVE_TOKEN", ""))
    rules = load_rules()
    universe = read_universe(cfg.get("universe_us") or HERE / "universe_us.txt")
    try:
        watch = site.watch(market)
    except Exception:  # noqa: BLE001 — 배포 전 시험 실행에서는 사이트에 경로가 아직 없을 수 있다
        if not args.dry_run:
            raise
        progress("관심 목록을 읽지 못해 기준 묶음만 점검합니다(시험 실행)")
        watch = []
    tickers = universe + [t for t in watch if t not in universe]
    progress(f"대상 {len(tickers)}종목 (관심 {len(watch)}종목)")

    uni = set(universe)
    records, failed, failed_uni, failed_watch = [], 0, 0, []
    delay = float(cfg.get("request_delay", 0.3))
    for i, t in enumerate(tickers, 1):
        try:
            # 받는 쪽 라이브러리가 종목 기호를 print·경고·로그로 흘려도 공개 Actions 로그에 나가지 않게 전부 삼킨다
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw = fetch(t)
            records.append(build_record(raw))
        except Exception as exc:  # noqa: BLE001 — 한 종목 실패는 세고 넘어간다(종목 이름은 로그에 남기지 않는다)
            failed += 1
            if t in uni:
                failed_uni += 1
            if t in watch:
                failed_watch.append(t)
            print(f"  · 수집 실패 1건: {type(exc).__name__}")
        if i % 25 == 0:
            progress(f"수집 {i}/{len(tickers)}")
        if delay:
            time.sleep(delay)
    # 기준 묶음(universe)만 실패율을 센다 — 관심 종목에 잘못된 기호가 섞여도 판 갱신이 멈추지 않게
    if not records or (uni and failed_uni / len(uni) > float(cfg.get("max_fail_ratio", 0.2))):
        raise RuntimeError(f"자료를 받지 못한 종목이 너무 많아요 ({failed_uni}/{len(uni)})")

    # 업종 중앙값·비교 회사는 기준 묶음만으로 — 관심 목록이 바뀌어도 기준이 흔들리지 않게
    base = [r for r in records if r["t"] in uni]
    med = medians(base, rules.get("sector_min", 5))
    as_of = max(r["as_of"] for r in records)
    # 공시(8-K) — 받지 못해도 계속한다(사건 관점은 가격 조건만 남는다). 실패 내용엔 회사·종목이 들어 있어 건수만 센다
    if filings_for is None:
        ua = os.environ.get("SEC_USER_AGENT", "").strip()
        if ua:
            filings_for = Edgar(ua).filings
        else:
            progress("공시 출처 설정(SEC_USER_AGENT)이 없어 가격 조건만으로 사건을 봅니다")
    ev_days = int(rules["lenses"]["event"]["days"])
    since = (_date.fromisoformat(as_of) - timedelta(days=ev_days)).isoformat()
    events: dict[str, list] = {}
    if filings_for:
        progress("공시 확인")
        got = lost = 0
        budget, t0 = float(cfg.get("filings_budget_sec", 480)), clock()
        for i, r in enumerate(records):
            if clock() - t0 > budget:   # 공시 서버가 느려 실행이 끝없이 늘어지지 않게
                progress(f"공시를 받지 못해 남은 {len(records) - i}종목은 가격 조건만 봅니다 (시간 초과)")
                break
            try:
                events[r["t"]] = classify(filings_for(r["t"], since), as_of, ev_days)
                got += 1
            except Exception:  # noqa: BLE001 — 종목 이름·오류 내용은 로그에 남기지 않는다
                lost += 1
                if lost >= 5 and not got:   # 처음부터 계속 막히면 나머지는 묻지 않는다
                    progress("공시를 받지 못해 가격 조건만으로 사건을 봅니다")
                    break
        else:
            if lost:
                progress(f"공시를 받지 못해 건너뛴 종목 {lost}건")

    rows, docs = [], []
    hits = {k: [] for k in LENS_ORDER}
    candidates = 0
    for r in records:
        checks = run_checks(r, med, rules)
        ev = events.get(r["t"], [])
        lens = lenses(r, checks, ev, rules)
        if r["t"] in uni and r["as_of"] == as_of:   # 기록·후보는 기준 묶음의 그날 자료만 — 관심 종목·오래된 자료는 판에만 보인다
            candidates += bool(lens)
            for x in lens:
                hits[x["id"]].append({"t": r["t"], "close": r["price"]})
        rows.append(board_row(r, checks, lens))
        docs.append({"market": market, "as_of": r["as_of"], "rec": r, "checks": checks, "diag": diag(checks),
                     "peers": peers(r, base), "ref": ref_for(r, med, rules.get("sector_min", 5)), "lenses": lens, "events": ev})
    board = {"market": market, "as_of": as_of, "generated_at": datetime.now(KST).isoformat(timespec="seconds"), "rows": rows, "medians": med,
             "missing": failed_watch,  # missing: 관심 종목 중 받지 못한 것 — 사이트 저장 공간에만 간다(로그·상태 파일에는 건수만)
             "lens_info": lens_info(rules)}

    # 관점 기록(§5.3) — 걸린 종목과 그날 종가, 견줄 지수 종가. 채점은 나중 단계에서 이 기록으로 한다
    index = None
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            spy = fetch("SPY")
        if spy["closes"][-1][0] == as_of:
            index = {"t": "SPY", "close": round(float(spy["closes"][-1][1]), 2)}
    except Exception:  # noqa: BLE001
        progress("지수 종가를 받지 못했습니다(기록에는 비워 둡니다)")
    lens_log = {"market": market, "date": as_of, "index": index, "hits": hits}

    if not args.dry_run:
        progress("저장")
        for d in docs:   # 종목 자료를 먼저 — 판이 가리키는 자료가 중간에 끊겨도 이미 있도록
            site.ingest(market, "ticker", d, ticker=d["rec"]["t"])
        site.ingest(market, "board", board)
        site.ingest(market, "lens", lens_log, date=as_of)

    n_warn = sum(1 for row in rows if row["n_warn"])
    return {
        "counts": {"checked": len(records), "watch": len(watch), "failed": failed, "failed_watch": sum(1 for t in failed_watch if t not in uni),
                   "candidates": candidates},
        "lines": [f"기준일 {as_of}", f"경고가 하나라도 있는 종목 {n_warn}개", f"관점에 걸린 종목 {candidates}개"],
        "tasks": {"collect": (True, f"{len(records)}종목 수집, 실패 {failed}건"), "check": (True, f"점검표 {len(rows)}종목, 관심 {len(watch)}종목"),
                  "discover": (True, f"후보 {candidates}종목 · " + " ".join(f"{LENS_LABEL[k]} {len(hits[k])}" for k in LENS_ORDER))},
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="받아서 계산만 하고 보내지 않는다")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"), help="설정 파일 경로")
    p.add_argument("--market", default="us", choices=["us"], help="시장 (1단계는 미국만)")
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_summary(counts: dict, elapsed_sec: float) -> str:
    names = {"checked": "점검", "watch": "관심", "failed": "실패", "failed_watch": "관심 실패", "candidates": "후보"}
    parts = [f"{names[k]} {v}건" for k, v in counts.items() if k in names]
    parts.append(f"{elapsed_sec / 60:.1f}분" if elapsed_sec >= 60 else f"{int(elapsed_sec)}초")
    return ", ".join(parts)


def build_tasks(cfg: dict, task_results: dict) -> list[dict]:
    out = []
    for tid in cfg.get("tasks") or []:
        ok, text = task_results.get(tid, (True, ""))
        out.append({"id": tid, "status": "done" if ok else "error", "summary": text})
    return out


def _report(cfg: dict, **kw) -> None:
    repo = (cfg.get("office_repo") or "").strip()
    if repo and report_status:
        report_status(repo, automation_id=AUTOMATION_ID, name=AUTOMATION_NAME, dept=DEPT,
                      next_run=cfg.get("next_run", ""), link=cfg.get("result_link", ""),
                      workspace=cfg.get("office_workspace", "home"), **kw)


def run(argv: list[str], work=None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config)
    started_at = datetime.now(KST).isoformat(timespec="seconds")
    started = time.monotonic()
    work = work or do_work
    progress = lambda m: print(f"  · {m}")  # noqa: E731
    try:
        result = work(cfg, args, progress)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        summary = to_korean(exc)
        detail = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(f"{summary} ({detail})", file=sys.stderr)
        if not args.dry_run:
            _report(cfg, ok=False, summary=summary, log_lines=[summary, detail], started_at=started_at,
                    duration_sec=int(time.monotonic() - started))
        return 1
    counts = dict(result.get("counts") or {})
    tasks = dict(result.get("tasks") or {})
    ok = all(v[0] for v in tasks.values())
    summary = build_summary(counts, time.monotonic() - started)
    print(summary)
    if not args.dry_run:
        _report(cfg, ok=ok, summary=summary, counts=counts, log_lines=[summary] + list(result.get("lines") or [])[:4],
                tasks=build_tasks(cfg, tasks), started_at=started_at, duration_sec=int(time.monotonic() - started))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
