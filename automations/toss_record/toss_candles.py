"""토스증권 1분봉 백필 — 국내 2022-11-23 부터, 200봉/호출·초당 20건. (종목, 날짜) 조각을 KIS 분봉과 같은 열 이름으로 저장해 분석 코드를 그대로 쓴다.

사용:
  python automations/toss_record/toss_candles.py --targets <csv(ticker,date)> [--stop-at 08:30]     # KIS 백필과 같은 목표 목록
  python automations/toss_record/toss_candles.py --codes 005930 --since 2025-09-01 --until 2025-09-30
  python automations/toss_record/toss_candles.py --universe --since 2025-10-01                       # 시총 범위 안 종목 전부(kis_universe)
- 저장: %LOCALAPPDATA%\\toss-record\\minutes\\YYYY-MM-DD\\<ticker>.parquet, 열 = KIS 와 동일(stck_bsop_date·stck_cntg_hour·stck_prpr·stck_oprc·stck_hgpr·stck_lwpr·cntg_vol·acml_tr_pbmn).
  토스 timestamp 는 봉 '종료' 시각(09:01 봉 = 09:00:00~09:00:59 체결) → stck_cntg_hour 는 봉 시작 시각(HHMM00)으로 바꿔 KIS(봉 시작 기준)와 맞춘다. acml_tr_pbmn 은 토스에 없어 빈 값.
  기본은 정규장(09:00~15:30 시작 봉)만 남긴다(--all-sessions 로 08:01~20:00 전부). KRX+NXT 통합 거래량이라 KIS(KRX 만)보다 크다.
- 진행: minutes/done.txt (ticker,date). 한 종목의 여러 날짜를 한 번에 받으므로 목표 목록을 종목별로 묶어 호출 수를 줄인다(1년치 ≈ 475호출 ≈ 25초).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1])); sys.path.insert(0, str(HERE.parent / "kis_record"))
import toss_rest as tr  # noqa: E402
from live_post import Heart  # noqa: E402
from record import KeepAwake, Lock, log, notify, now_kst  # noqa: E402

DEFAULT_CFG = HERE.parents[1] / "ai-home" / "02_주식신호" / "config.yaml"
MIN_COLS = ["stck_bsop_date", "stck_cntg_hour", "stck_prpr", "stck_oprc", "stck_hgpr", "stck_lwpr", "cntg_vol", "acml_tr_pbmn"]


def to_kis_rows(candles: list[dict], regular_only: bool = True) -> dict[str, list[dict]]:
    """토스 봉(최신순 아님, 아무 순서) → 날짜별 KIS 열 행 목록(봉 시작 시각 기준, 시간순)."""
    by_day: dict[str, list[dict]] = defaultdict(list)
    for c in candles:
        ts = c["timestamp"]                      # 2026-09-29T10:05:00.000+09:00 (봉 종료)
        end = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        start = end - timedelta(minutes=1)
        hhmm = start.strftime("%H%M")
        if regular_only and not ("0900" <= hhmm <= "1530"):
            continue
        by_day[start.strftime("%Y%m%d")].append({
            "stck_bsop_date": start.strftime("%Y%m%d"), "stck_cntg_hour": hhmm + "00",
            "stck_prpr": c.get("closePrice", ""), "stck_oprc": c.get("openPrice", ""), "stck_hgpr": c.get("highPrice", ""), "stck_lwpr": c.get("lowPrice", ""),
            "cntg_vol": c.get("volume", ""), "acml_tr_pbmn": ""})
    for d in by_day.values():
        d.sort(key=lambda r: r["stck_cntg_hour"])
    return dict(by_day)


def save_day(root: Path, ticker: str, date: str, rows: list[dict]) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq
    d = root / f"{date[:4]}-{date[4:6]}-{date[6:]}"; d.mkdir(parents=True, exist_ok=True)
    tbl = pa.table({c: pa.array([str(r.get(c, "")) for r in rows], pa.string()) for c in MIN_COLS})
    p = d / f"{ticker}.parquet"; pq.write_table(tbl, p, compression="zstd")
    return p


def load_done(root: Path) -> set[tuple[str, str]]:
    p = root / "done.txt"
    if not p.exists():
        return set()
    return {(a, b) for a, b in (ln.strip().split(",", 1) for ln in p.read_text(encoding="utf-8").splitlines() if "," in ln)}


def run(ses: tr.Session, root: Path, wanted: dict[str, set[str]], regular_only: bool, stop_at: datetime | None, adjusted: bool | None, heart: Heart | None = None) -> dict:
    """wanted: ticker → {YYYYMMDD,...}. 종목별로 가장 오래된 날짜까지 한 번에 받아 필요한 날짜만 저장."""
    done = load_done(root)
    stats = {"tickers": 0, "pieces": 0, "empty": 0, "errors": 0, "rows": 0}
    t0 = time.time(); calls0 = ses.calls
    with open(root / "done.txt", "a", encoding="utf-8") as donef:
        for k, (ticker, dates) in enumerate(sorted(wanted.items()), 1):
            todo = sorted(d for d in dates if (ticker, d) not in done)
            if not todo:
                continue
            if stop_at and now_kst() >= stop_at:
                log(f"정한 시각({stop_at:%H:%M}) — 중단"); break
            since = f"{todo[0][:4]}-{todo[0][4:6]}-{todo[0][6:]}"
            last = todo[-1]
            before = f"{last[:4]}-{last[4:6]}-{last[6:]}T23:59:00+09:00"
            try:
                out: list[dict] = []; bf = before
                for _ in range(2000):
                    d = ses.candles(ticker, "1m", 200, bf, adjusted)
                    rows = d.get("candles") or []
                    if not rows:
                        break
                    out.extend(rows); bf = d.get("nextBefore")
                    if not bf or rows[-1]["timestamp"][:10] < since:
                        break
            except tr.TossError as exc:
                stats["errors"] += 1
                if stats["errors"] <= 20:
                    log(f"  {ticker}: {exc}")
                if "stock-not-found" in str(exc) or "404" in str(exc):
                    for dte in todo:
                        donef.write(f"{ticker},{dte}\n")      # 없는 종목(상장폐지 등)은 다시 시도하지 않는다
                    donef.flush()
                if stats["errors"] > 200:
                    log("오류가 너무 많아 중단"); break
                continue
            by_day = to_kis_rows(out, regular_only)
            for dte in todo:
                rows = by_day.get(dte, [])
                if rows:
                    save_day(root, ticker, dte, rows); stats["rows"] += len(rows); stats["pieces"] += 1
                else:
                    stats["empty"] += 1
                donef.write(f"{ticker},{dte}\n")
            donef.flush()
            stats["tickers"] += 1
            if heart:
                heart.beat("running", f"1분봉 {k}/{len(wanted)}종목 · 조각 {stats['pieces']:,}")
            if k % 20 == 0:
                el = time.time() - t0
                log(f"  {k}/{len(wanted)} 종목, 호출 {ses.calls - calls0}, 한도 초과 {ses.rate_hits}, {el/60:.0f}분, 남은 예상 {(len(wanted)-k)*el/k/60:.0f}분")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CFG))
    ap.add_argument("--out", default=str(tr.DEFAULT_OUT / "minutes"))
    ap.add_argument("--targets", default="", help="csv(ticker,date) — KIS 백필과 같은 목록")
    ap.add_argument("--codes", default="")
    ap.add_argument("--universe", action="store_true", help="kis_universe 시총 범위 안 종목 전부")
    ap.add_argument("--cap-min", type=float, default=300); ap.add_argument("--cap-max", type=float, default=5000)
    ap.add_argument("--since", default=tr.HISTORY_START_KR); ap.add_argument("--until", default="")
    ap.add_argument("--all-sessions", action="store_true"); ap.add_argument("--adjusted", choices=["true", "false"], default="false")
    ap.add_argument("--stop-at", default="")
    a = ap.parse_args()
    root = Path(a.out); root.mkdir(parents=True, exist_ok=True)
    tr.load_secrets(a.config)
    wanted: dict[str, set[str]] = defaultdict(set)
    if a.targets:
        import pandas as pd
        df = pd.read_csv(a.targets, dtype=str)
        for t, d in zip(df["ticker"], df["date"]):
            wanted[str(t).zfill(6)].add(str(d))
    else:
        if a.codes:
            codes = [c.strip().zfill(6) for c in a.codes.split(",") if c.strip()]
        elif a.universe:
            import kis_universe as ku
            uni = ku.build_universe(ku.fetch_listing(), [], [], tier_a_size=0, cap_min_eok=a.cap_min, cap_max_eok=a.cap_max)
            codes = uni.tier_a + uni.tier_b
        else:
            raise SystemExit("--targets, --codes 또는 --universe")
        import pandas as pd
        end = a.until or now_kst().strftime("%Y-%m-%d")
        days = [d.strftime("%Y%m%d") for d in pd.bdate_range(a.since, end)]      # 휴장일은 빈 조각으로 기록됨
        for c in codes:
            wanted[c].update(days)
    stop_at = None
    if a.stop_at:
        hh, mm = a.stop_at.split(":")
        stop_at = now_kst().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if stop_at <= now_kst():
            stop_at += timedelta(days=1)
    with Lock(root.parent / "rest.lock"):
        with KeepAwake():
            ses = tr.Session(log=log)
            log(f"목표 {sum(len(v) for v in wanted.values())}조각 / {len(wanted)}종목")
            t0 = time.time()
            heart = Heart(a.config, "candles", log=log); heart.beat("running", f"1분봉 시작 · 목표 {sum(len(v) for v in wanted.values())}조각")
            try:
                st = run(ses, root, wanted, not a.all_sessions, stop_at, a.adjusted == "true", heart)
            except Exception as exc:  # noqa: BLE001
                heart.end("error", f"1분봉 실패: {type(exc).__name__}"); raise
            line = f"토스 분봉: 종목 {st['tickers']}, 조각 {st['pieces']}(빈 {st['empty']}, 오류 {st['errors']}), 행 {st['rows']:,}, 호출 {ses.calls}, 한도 초과 {ses.rate_hits}, {(time.time()-t0)/60:.0f}분"
            log(line); heart.end("done", f"1분봉 조각 {st['pieces']:,}개(빈 {st['empty']}, 오류 {st['errors']})")
            (root / "last_summary.json").write_text(json.dumps({"time": now_kst().isoformat(), **st, "calls": ses.calls}, ensure_ascii=False), encoding="utf-8")
            if st["pieces"] > 500:
                notify(a.config, line)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        log(f"실패: {type(exc).__name__}: {str(exc)[:80]}")
        sys.exit(5)
