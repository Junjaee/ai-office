"""1분봉 수집 — 한투 '주식일별분봉조회'(1년 보관)로 (종목, 날짜) 의 하루 1분봉을 받아 Parquet 으로 쌓는다.

사용:
  python kis_minutes.py --targets targets.csv          # 백필: csv(ticker,date) 목록을 순서대로(재시작 가능)
  python kis_minutes.py --eod                          # 오늘 전 종목(장 마감 뒤, 약 2,575×4 호출 ≈ 3시간)
  python kis_minutes.py --eod --date 20260925 --n 300  # 특정 날짜, 거래대금 상위 300 만
- 한도 약 1건/초(실측) → 하루 1종목 = 4호출 ≈ 4초. 하룻밤(10시간)에 약 9,000 (종목,날짜) 조각.
- 저장: %LOCALAPPDATA%\\kis-record\\minutes\\YYYY-MM-DD\\<ticker>.parquet (열: 전부 문자열: stck_bsop_date·stck_cntg_hour·stck_prpr·stck_oprc·stck_hgpr·stck_lwpr·cntg_vol·acml_tr_pbmn).
  진행 상황은 minutes/done.txt (한 줄 = ticker,date). 이미 있는 조각은 건너뛴다.
- 목표 목록 만들기: python kis_minutes.py --make-targets events_A.csv --since 20251001 --before 20251001..  (아래 make_targets 참고)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import kis_client as kc  # noqa: E402
import kis_rest as kr  # noqa: E402
from record import DEFAULT_CFG, DEFAULT_OUT, KeepAwake, Lock, log, notify, now_kst  # noqa: E402

MIN_COLS = ["stck_bsop_date", "stck_cntg_hour", "stck_prpr", "stck_oprc", "stck_hgpr", "stck_lwpr", "cntg_vol", "acml_tr_pbmn"]


def save_day(root: Path, ticker: str, date: str, rows: list[dict]) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq
    d = root / f"{date[:4]}-{date[4:6]}-{date[6:]}"
    d.mkdir(parents=True, exist_ok=True)
    tbl = pa.table({c: pa.array([str(r.get(c, "")) for r in rows], pa.string()) for c in MIN_COLS})
    p = d / f"{ticker}.parquet"
    pq.write_table(tbl, p, compression="zstd")
    return p


def load_done(root: Path) -> set[tuple[str, str]]:
    p = root / "done.txt"
    if not p.exists():
        return set()
    return {tuple(ln.strip().split(",")) for ln in p.read_text(encoding="utf-8").splitlines() if "," in ln}


def make_targets(events_csv: str, since: str, until: str, pre_days: int, post_days: int, n_events: int, seed: int,
                 trading_days: list[str], universe: list[str], exclude_windows: dict, out_csv: str) -> pd.DataFrame:
    """사건 표(ticker,t0) → (ticker,date) 목표 목록. 사건마다 짝(같은 날, 사건 없는 다른 종목)을 하나 붙여 같은 날짜 창을 받는다.
    exclude_windows: {ticker: [(start,end), ...]} 사건 창(YYYYMMDD) — 짝 종목이 그 안에 있으면 안 됨."""
    ev = pd.read_csv(events_csv, parse_dates=["t0"])
    ev = ev[(ev["t0"] >= pd.Timestamp(since)) & (ev["t0"] <= pd.Timestamp(until))].copy()
    ev["ticker"] = ev["ticker"].astype(str).str.zfill(6)
    ev = ev.sort_values("t0", ascending=False).drop_duplicates(["ticker", "t0"])
    rng = random.Random(seed)
    if n_events and len(ev) > n_events:
        ev = ev.sample(n_events, random_state=seed)
    td = trading_days
    pos = {d: i for i, d in enumerate(td)}
    rows = []
    for _, r in ev.iterrows():
        t0 = r["t0"].strftime("%Y%m%d")
        if t0 not in pos:
            continue
        i = pos[t0]
        days = td[max(0, i - pre_days): i + post_days + 1]
        # 짝: 같은 t0 에 사건 창이 없는 종목
        for _ in range(50):
            c = rng.choice(universe)
            if c == r["ticker"]:
                continue
            bad = any(s <= t0 <= e for s, e in exclude_windows.get(c, []))
            if not bad:
                break
        else:
            c = None
        for d in days:
            rows.append({"ticker": r["ticker"], "date": d, "role": "event", "t0": t0, "pair": c or ""})
            if c:
                rows.append({"ticker": c, "date": d, "role": "control", "t0": t0, "pair": r["ticker"]})
    df = pd.DataFrame(rows).drop_duplicates(["ticker", "date"])
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return df


def run_targets(ses: kr.Session, root: Path, targets: pd.DataFrame, budget_calls: int = 0, stop_at: datetime | None = None) -> dict:
    done = load_done(root)
    todo = [(str(t).zfill(6), str(d)) for t, d in zip(targets["ticker"], targets["date"]) if (str(t).zfill(6), str(d)) not in done]
    log(f"목표 {len(targets)}조각 중 남은 {len(todo)}조각")
    stats = {"done": 0, "empty": 0, "errors": 0, "rows": 0}
    t0 = time.time()
    with open(root / "done.txt", "a", encoding="utf-8") as donef:
        for k, (ticker, date) in enumerate(todo, 1):
            if budget_calls and ses.calls >= budget_calls:
                log("호출 예산 소진 — 중단"); break
            if stop_at and now_kst() >= stop_at:
                log(f"정한 시각({stop_at:%H:%M}) — 중단"); break
            try:
                rows = ses.day_minutes(ticker, date)
            except kr.KISError as exc:
                stats["errors"] += 1
                if stats["errors"] <= 20:
                    log(f"  {ticker} {date}: {exc}")
                if stats["errors"] > 200:
                    log("오류가 너무 많아 중단"); break
                continue
            if rows:
                save_day(root, ticker, date, rows); stats["rows"] += len(rows)
            else:
                stats["empty"] += 1
            donef.write(f"{ticker},{date}\n"); donef.flush()
            stats["done"] += 1
            if k % 50 == 0:
                el = time.time() - t0
                log(f"  {k}/{len(todo)} 조각, 호출 {ses.calls}, 한도 초과 {ses.rate_hits}, {el/60:.0f}분, 남은 예상 {(len(todo)-k)*el/k/3600:.1f}시간")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CFG))
    ap.add_argument("--out", default=str(DEFAULT_OUT / "minutes"))
    ap.add_argument("--interval", type=float, default=1.5)
    ap.add_argument("--targets", default="")
    ap.add_argument("--eod", action="store_true")
    ap.add_argument("--date", default="")
    ap.add_argument("--n", type=int, default=0, help="--eod 때 거래대금 상위 n 종목만(0=전 종목)")
    ap.add_argument("--budget", type=int, default=0, help="이번 실행 호출 상한(0=무제한)")
    ap.add_argument("--stop-at", default="", help="이 시각(HH:MM, 다음날 포함)이 되면 멈춘다 — 아침 스냅샷과 겹치지 않게")
    a = ap.parse_args()
    root = Path(a.out); root.mkdir(parents=True, exist_ok=True)
    kc.load_secrets(a.config)
    with Lock(root.parent / "rest.lock"):      # 스냅샷과 같은 계좌 한도를 쓰므로 REST 작업은 하나만
        with KeepAwake():
            try:
                ses = kr.Session(interval=a.interval, log=log)
            except kr.KISError as exc:
                log(str(exc)); return 4
            if a.targets:
                targets = pd.read_csv(a.targets, dtype=str)
            elif a.eod:
                import kis_pick
                date = a.date or now_kst().strftime("%Y%m%d")
                codes = kis_pick.top_by_trading_value(a.n) if a.n else None
                if codes is None:
                    meta = pd.read_csv(HERE / "universe.csv", dtype=str)["ticker"].tolist() if (HERE / "universe.csv").exists() else kis_pick.top_by_trading_value(3000, pages_per_market=30)
                    codes = meta
                targets = pd.DataFrame({"ticker": codes, "date": date})
            else:
                raise SystemExit("--targets 또는 --eod")
            stop_at = None
            if a.stop_at:
                hh, mm = a.stop_at.split(":")
                stop_at = now_kst().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                if stop_at <= now_kst():
                    stop_at = stop_at + pd.Timedelta(days=1)
            t0 = time.time()
            st = run_targets(ses, root, targets, a.budget, stop_at)
            line = f"분봉 수집: 조각 {st['done']}개(빈 {st['empty']}, 오류 {st['errors']}), 행 {st['rows']:,}, 호출 {ses.calls}, 한도 초과 {ses.rate_hits}, {(time.time()-t0)/60:.0f}분"
            log(line)
            (root / "last_summary.json").write_text(json.dumps({"time": now_kst().isoformat(), **st, "calls": ses.calls}, ensure_ascii=False), encoding="utf-8")
            if not a.targets or st["done"] > 500:
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
