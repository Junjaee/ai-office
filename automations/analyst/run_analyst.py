"""주식 분석 자동화 — 미국·국내 종목 시세·재무를 받아 점검표를 계산하고 사이트 저장 공간에 올린다.

사용:
  python run_analyst.py                      # 실제 실행 (끝나면 상태 파일 커밋·push)
  python run_analyst.py --dry-run            # 받아서 계산만 하고 보내지 않는다
  옵션: --config 경로, --market us|kr

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
from analyst_score import merge_history, score_lenses  # noqa: E402
from analyst_sources_edgar import Edgar  # noqa: E402
from analyst_sources_kr import fetch_raw_kr  # noqa: E402
from analyst_sources_news import fetch_titles  # noqa: E402
from analyst_sources_us import fetch_raw  # noqa: E402

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "analyst"
AUTOMATION_NAME = "주식 분석"
DEPT = "finance"
HERE = Path(__file__).resolve().parent

# 시장별로 다른 것은 이 표 하나로 — universe 는 대상 파일, index 는 야후 기호, index_label 은 기록에 적는 이름
MARKETS = {
    "us": {"universe": "universe_us.txt", "index": "SPY", "index_label": "SPY", "locale": "us"},
    "kr": {"universe": "universe_kr.txt", "index": "^KS11", "index_label": "KOSPI", "locale": "kr"},
}
MARKET_LABEL = {"us": "미국", "kr": "국내"}
NO_KR_FILINGS = "국내 공시는 아직 받지 않아 가격 조건만으로 사건을 봅니다"

# yfinance 는 받지 못한 종목의 기호를 직접 로그에 찍는다 — 공개 저장소의 Actions 로그에 남지 않게 막는다
logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logging.getLogger("yfinance").propagate = False


def read_universe_meta(path: str | Path) -> dict[str, dict]:
    """{기호: {"exch", "name"}} — 한 줄은 `기호 [거래소]  # 이름`. 미국 파일(이름·거래소 없음)도 읽는다(그때 None)."""
    out: dict[str, dict] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        body, _, name = line.partition("#")
        parts = body.split()
        if parts and parts[0].upper() not in out:
            out[parts[0].upper()] = {"exch": parts[1].upper() if len(parts) > 1 else None, "name": name.strip() or None}
    return out


def read_universe(path: str | Path) -> list[str]:
    return list(read_universe_meta(path))


SCORE_SKIPPED = "관점 기록을 읽지 못해 오늘 채점은 건너뜁니다"
SCORE_NO_INDEX = "지수 종가가 기준일 것이 아니라 오늘 채점과 기록을 건너뜁니다"
SCORE_FAILED = "관점 채점 계산에 실패해 오늘 채점은 건너뜁니다"


@contextlib.contextmanager
def _quiet():
    """받는 쪽 라이브러리가 종목 기호를 print·경고·로그로 흘려도 공개 Actions 로그에 나가지 않게 전부 삼킨다."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        yield


def _score(site, market: str, as_of: str, hits: dict, closes: dict, spy_closes, progress):
    """(관점 채점 결과, 사이트에 보낼 관점 기록). 지수가 오늘 것이 아니거나 기록을 못 읽으면 (None, None) — 기록을 덮어쓰지 않는다."""
    if not spy_closes or spy_closes[-1][0] != as_of:
        progress(SCORE_NO_INDEX)
        return None, None
    try:
        with _quiet():
            history = site.get_view(market, "lenshist").get("history")   # 아직 없으면 None — 실패가 아니다
    except Exception:  # noqa: BLE001 — 오류 내용엔 주소가 들어 있을 수 있다
        progress(SCORE_SKIPPED)
        return None, None
    merged = merge_history(history, as_of, {k: [x["t"] for x in v] for k, v in hits.items()})
    try:
        return score_lenses(merged, closes, spy_closes), merged
    except Exception:  # noqa: BLE001 — 채점이 죽어도 기록은 올린다(오류 내용은 남기지 않는다)
        progress(SCORE_FAILED)
        return None, merged


def _news(records: list, watch: list, as_of: str, news, delay: float, progress, budget: float = 180, clock=time.monotonic, locale: str = "us") -> tuple[dict, int]:
    """관심 종목의 기사 제목 {기호: [...]}(받은 종목만 — 제목이 0건이어도 받은 것이다), 받은 종목 수. 실패는 세고 넘어간다(이름·오류 내용은 남기지 않는다)."""
    out, lost, streak, stopped, t0 = {}, 0, 0, False, clock()
    for i, r in enumerate(records):
        if r["t"] not in watch:
            continue
        if clock() - t0 > budget:   # 기사 서버가 느려 실행이 끝없이 늘어지지 않게
            progress(f"기사 제목을 받지 못해 남은 {sum(1 for x in records[i:] if x['t'] in watch)}종목은 건너뜁니다 (시간 초과)")
            stopped = True
            break
        name = (r.get("name_local") if locale == "kr" else None) or r.get("name")
        if not name:
            lost += 1
            continue
        try:
            with _quiet():
                out[r["t"]] = news(name, as_of, locale=locale) if locale != "us" else news(name, as_of)
            streak = 0
        except Exception:  # noqa: BLE001
            lost += 1
            streak += 1
            if streak >= 5:   # 연달아 막히면 나머지는 묻지 않는다
                progress("기사 제목을 받지 못해 나머지 종목은 묻지 않습니다")
                stopped = True
                break
        if delay:
            time.sleep(delay)
    if lost and not stopped:
        progress(f"기사 제목을 받지 못해 건너뛴 종목 {lost}건")
    return out, len(out)


def do_work(cfg: dict, args: argparse.Namespace, progress, fetch=None, site: Site | None = None, filings_for=None, clock=time.monotonic, news=fetch_titles) -> dict:
    market = getattr(args, "market", "us") or "us"
    mk = MARKETS[market]
    if site is None:
        site = Site(cfg["site_url"], token=os.environ.get("LIVE_TOKEN", ""))
    rules = load_rules()
    meta = read_universe_meta(cfg.get(f"universe_{market}") or HERE / mk["universe"])
    universe = list(meta)
    if fetch is None:   # 주입된 수집기가 있으면 그것이 먼저(시험). 국내는 거래소·이름을 함께 넘기고, 지수는 야후 기호 그대로 받는다
        fetch = fetch_raw if market == "us" else lambda t: fetch_raw(t) if t == mk["index"] else fetch_raw_kr(t, meta.get(t))
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
    closes: dict[str, list] = {}   # 기준 묶음의 1년 종가 — 관점 채점용
    delay = float(cfg.get("request_delay", 0.3))
    for i, t in enumerate(tickers, 1):
        try:
            # 받는 쪽 라이브러리가 종목 기호를 print·경고·로그로 흘려도 공개 Actions 로그에 나가지 않게 전부 삼킨다
            with _quiet():
                raw = fetch(t)
            records.append(build_record(raw))
            if t in uni:
                closes[t] = raw["closes"]
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
    as_of = max(r["as_of"] for r in (base or records))   # 기준일은 기준 묶음에서만 — 관심 종목의 더 늦은 날짜가 판 날짜를 끌어가지 않게
    # 공시(8-K) — 받지 못해도 계속한다(사건 관점은 가격 조건만 남는다). 실패 내용엔 회사·종목이 들어 있어 건수만 센다
    if filings_for is None:
        ua = os.environ.get("SEC_USER_AGENT", "").strip()
        if market == "kr":   # 국내는 EDGAR 를 시도하지 않는다
            progress(NO_KR_FILINGS)
        elif ua:
            filings_for = Edgar(ua).filings
        else:
            progress("공시 출처 설정(SEC_USER_AGENT)이 없어 가격 조건만으로 사건을 봅니다")
    ev_days = int(rules["lenses"]["event"]["days"])
    since = (_date.fromisoformat(as_of) - timedelta(days=ev_days)).isoformat()
    events: dict[str, list] = {}
    filings_ok = False   # 설정돼 있고 끝까지 하나도 빠짐없이 받았을 때만 참 — 화면이 "공시를 확인했다"고 말해도 되는지
    if filings_for:
        progress("공시 확인")
        lost = streak = 0
        stopped = False
        budget, t0 = float(cfg.get("filings_budget_sec", 480)), clock()
        for i, r in enumerate(records):
            if clock() - t0 > budget:   # 공시 서버가 느려 실행이 끝없이 늘어지지 않게
                progress(f"공시를 받지 못해 남은 {len(records) - i}종목은 가격 조건만 봅니다 (시간 초과)")
                stopped = True
                break
            try:
                events[r["t"]] = classify(filings_for(r["t"], since), as_of, ev_days)
                streak = 0
            except Exception:  # noqa: BLE001 — 종목 이름·오류 내용은 로그에 남기지 않는다
                lost += 1
                streak += 1
                if streak >= 10:   # 연달아 막히면 나머지는 묻지 않는다(중간에 한 번이라도 되면 다시 센다)
                    progress("공시를 받지 못해 가격 조건만으로 사건을 봅니다")
                    stopped = True
                    break
        if lost and not stopped:
            progress(f"공시를 받지 못해 건너뛴 종목 {lost}건")
        filings_ok = not lost and not stopped

    rows, docs = [], []
    hits = {k: [] for k in LENS_ORDER}
    candidates = 0
    for r in records:
        checks = run_checks(r, med, rules)
        ev = events.get(r["t"], [])
        lens = []
        if r["t"] in uni and r["as_of"] == as_of:   # 관점은 기준 묶음의 그날 자료만 — 관심 종목·오래된 자료는 점검표와 공시만 보인다
            lens = lenses(r, checks, ev, rules)
            candidates += bool(lens)
            for x in lens:
                hits[x["id"]].append({"t": r["t"], "close": r["price"]})
        rows.append(board_row(r, checks, lens))
        docs.append({"market": market, "as_of": r["as_of"], "rec": r, "checks": checks, "diag": diag(checks),
                     "peers": peers(r, base), "ref": ref_for(r, med, rules.get("sector_min", 5)), "lenses": lens, "events": ev, "news": None})   # news None = 받지 못했거나 받지 않음, [] = 받았는데 0건
    board = {"market": market, "as_of": as_of, "generated_at": datetime.now(KST).isoformat(timespec="seconds"), "rows": rows, "medians": med,
             "missing": failed_watch,  # missing: 관심 종목 중 받지 못한 것 — 사이트 저장 공간에만 간다(로그·상태 파일에는 건수만)
             "universe": len(uni), "filings_ok": filings_ok, "lens_info": lens_info(rules, filings_ok),
             "score_gate": {"min_n": int((rules.get("score") or {}).get("min_n", 30)), "min_days": int((rules.get("score") or {}).get("min_days", 20))}}
    discover = f"후보 {candidates}종목 · " + " ".join(f"{LENS_LABEL[k]} {len(hits[k])}" for k in LENS_ORDER)
    progress(discover)   # 건수만 — 시험 실행에서도 보이게

    # 관점 기록(§5.3) — 걸린 종목과 그날 종가, 견줄 지수 종가
    index, spy_closes = None, None
    try:
        with _quiet():
            spy_closes = fetch(mk["index"])["closes"]
        if spy_closes[-1][0] == as_of:
            index = {"t": mk["index_label"], "close": round(float(spy_closes[-1][1]), 2)}
    except Exception:  # noqa: BLE001
        progress("지수 종가를 받지 못했습니다(기록에는 비워 둡니다)")
    lens_log = {"market": market, "date": as_of, "index": index, "hits": hits}
    # 채점 — 쌓인 기록에 오늘 것을 덧붙여 걸린 뒤 수익률을 지수와 견준다. 시험 실행에서도 읽기는 한다(보내지는 않는다)
    board["lens_score"], lens_hist = _score(site, market, as_of, hits, closes, spy_closes, progress)

    # 관심 종목 기사 제목(해석할 때 읽을 자료) — 끄면 아무것도 받지 않는다
    news_n = 0
    if cfg.get("news_enabled"):
        titles, news_n = _news(records, set(watch), as_of, news, delay, progress, float(cfg.get("news_budget_sec", 180)), clock, mk["locale"])
        for d in docs:
            d["news"] = titles.get(d["rec"]["t"])

    if not args.dry_run:
        progress("저장")
        for d in docs:   # 종목 자료를 먼저 — 판이 가리키는 자료가 중간에 끊겨도 이미 있도록
            site.ingest(market, "ticker", d, ticker=d["rec"]["t"])
        site.ingest(market, "board", board)
        site.ingest(market, "lens", lens_log, date=as_of)
        if lens_hist is not None:
            site.ingest(market, "lenshist", lens_hist)
            site.ingest(market, "index", {"t": mk["index_label"], "closes": spy_closes})

    n_warn = sum(1 for row in rows if row["n_warn"])
    return {
        "counts": {"checked": len(records), "watch": len(watch), "failed": failed, "failed_watch": sum(1 for t in failed_watch if t not in uni),
                   "candidates": candidates, "news": news_n},
        "lines": [f"기준일 {as_of}", f"경고가 하나라도 있는 종목 {n_warn}개", f"관점에 걸린 종목 {candidates}개"]
                 + ([f"관심 종목 기사 제목 {news_n}종목"] if cfg.get("news_enabled") else []),
        "tasks": {"collect": (True, f"{len(records)}종목 수집, 실패 {failed}건"), "check": (True, f"점검표 {len(rows)}종목, 관심 {len(watch)}종목"),
                  "discover": (True, discover)},
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="받아서 계산만 하고 보내지 않는다")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"), help="설정 파일 경로")
    p.add_argument("--market", default="us", choices=list(MARKETS), help="시장 (us | kr)")
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_summary(counts: dict, elapsed_sec: float, market: str = "us") -> str:
    names = {"checked": "점검", "watch": "관심", "failed": "실패", "failed_watch": "관심 실패", "candidates": "후보"}
    parts = [f"{names[k]} {v}건" for k, v in counts.items() if k in names]
    parts.append(f"{elapsed_sec / 60:.1f}분" if elapsed_sec >= 60 else f"{int(elapsed_sec)}초")
    return f"{MARKET_LABEL[market]} · " + ", ".join(parts)


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
    summary = build_summary(counts, time.monotonic() - started, args.market)
    print(summary)
    if not args.dry_run:
        _report(cfg, ok=ok, summary=summary, counts=counts, log_lines=[summary] + list(result.get("lines") or [])[:4],
                tasks=build_tasks(cfg, tasks), started_at=started_at, duration_sec=int(time.monotonic() - started))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
