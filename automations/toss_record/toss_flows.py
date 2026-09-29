"""토스증권 일별 수급 시계열 백필 — 투자자별 매매동향(개인·외국인·기관 4분류+기관 세부 7, 2019-04~), 프로그램매매, 공매도(2019-04~), 신용(2023-04~), 대차(2021-04~).

사용:
  python automations/toss_record/toss_flows.py --universe                       # 시총 범위 안 종목 전부, 5종 다
  python automations/toss_record/toss_flows.py --codes 005930 --kinds investor-trading,short-selling --since 2020-01-01
  python automations/toss_record/toss_flows.py --all-listed                     # 코스피·코스닥 보통주 전부(토스 종목 목록)
- 저장: %USERPROFILE%\\ai-office-data\\toss-record\\flows\\<kind>\\<ticker>.parquet — 한 종목의 전 기간(최신순 아님, 날짜순), 중첩 필드는 평평하게(institution.breakdown.pension 등 → 점 연결 이름), 값은 전부 문자열.
- 호출: 100일/호출·초당 15건. 투자자별 7.5년 ≈ 19호출 → 2,600종목 ≈ 5만 호출 ≈ 55분. 5종 다 하면 약 3~4시간.
- 진행: flows/done.txt (kind,ticker). 다시 돌리면 이미 받은 종목은 건너뛴다(--refresh 로 다시 받음).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1])); sys.path.insert(0, str(HERE.parent / "kis_record"))
import toss_rest as tr  # noqa: E402
from live_post import Heart  # noqa: E402
from record import KeepAwake, Lock, log, notify, now_kst  # noqa: E402

DEFAULT_CFG = HERE.parents[1] / "ai-home" / "02_주식신호" / "config.yaml"
KINDS = ["investor-trading", "program-trades", "short-selling", "credit-trades", "securities-lending"]


def flatten(rec: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in rec.items():
        if isinstance(v, dict):
            out.update(flatten(v, f"{prefix}{k}."))
        elif isinstance(v, list):
            out[f"{prefix}{k}"] = json.dumps(v, ensure_ascii=False)
        else:
            out[f"{prefix}{k}"] = "" if v is None else str(v)
    return out


def save(root: Path, kind: str, ticker: str, records: list[dict]) -> Path:
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows = [flatten(r) for r in records]
    cols = sorted({k for r in rows for k in r}, key=lambda c: (c != "date", c))
    d = root / kind; d.mkdir(parents=True, exist_ok=True)
    tbl = pa.table({c: pa.array([r.get(c, "") for r in rows], pa.string()) for c in cols})
    p = d / f"{ticker}.parquet"; pq.write_table(tbl, p, compression="zstd")
    return p


def load_done(root: Path) -> set[tuple[str, str]]:
    p = root / "done.txt"
    if not p.exists():
        return set()
    return {(a, b) for a, b in (ln.strip().split(",", 1) for ln in p.read_text(encoding="utf-8").splitlines() if "," in ln)}


def run(ses: tr.Session, root: Path, codes: list[str], kinds: list[str], since: str | None, refresh: bool, stop_at=None, heart: Heart | None = None) -> dict:
    done = set() if refresh else load_done(root)
    stats = {"saved": 0, "empty": 0, "errors": 0, "rows": 0}
    t0 = time.time(); calls0 = ses.calls; total = len(codes) * len(kinds); k = 0
    with open(root / "done.txt", "a", encoding="utf-8") as donef:
        for ticker in codes:
            for kind in kinds:
                k += 1
                if (kind, ticker) in done:
                    continue
                if stop_at and now_kst() >= stop_at:
                    log(f"정한 시각({stop_at:%H:%M}) — 중단"); return stats
                try:
                    recs = ses.daily_series_all(ticker, kind, since)
                except tr.TossError as exc:
                    stats["errors"] += 1
                    if stats["errors"] <= 20:
                        log(f"  {ticker} {kind}: {exc}")
                    if "404" in str(exc) or "400" in str(exc):
                        donef.write(f"{kind},{ticker}\n"); donef.flush()
                    if stats["errors"] > 300:
                        log("오류가 너무 많아 중단"); return stats
                    continue
                if recs:
                    save(root, kind, ticker, recs); stats["saved"] += 1; stats["rows"] += len(recs)
                else:
                    stats["empty"] += 1
                donef.write(f"{kind},{ticker}\n"); donef.flush()
                if heart:
                    heart.beat("running", f"수급 {k}/{total} · 저장 {stats['saved']:,}")
                if k % 100 == 0:
                    el = time.time() - t0
                    log(f"  {k}/{total}, 호출 {ses.calls - calls0}, 한도 초과 {ses.rate_hits}, {el/60:.0f}분, 남은 예상 {(total-k)*el/k/60:.0f}분")
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CFG))
    ap.add_argument("--out", default=str(tr.DEFAULT_OUT / "flows"))
    ap.add_argument("--codes", default=""); ap.add_argument("--universe", action="store_true"); ap.add_argument("--all-listed", action="store_true")
    ap.add_argument("--cap-min", type=float, default=300); ap.add_argument("--cap-max", type=float, default=5000)
    ap.add_argument("--kinds", default=",".join(KINDS))
    ap.add_argument("--since", default="", help="이 날짜 이후만(비우면 제공되는 전 기간)")
    ap.add_argument("--refresh", action="store_true"); ap.add_argument("--stop-at", default="")
    a = ap.parse_args()
    root = Path(a.out); root.mkdir(parents=True, exist_ok=True)
    tr.load_secrets(a.config)
    kinds = [k.strip() for k in a.kinds.split(",") if k.strip() in KINDS]
    stop_at = None
    if a.stop_at:
        hh, mm = a.stop_at.split(":")
        stop_at = now_kst().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if stop_at <= now_kst():
            stop_at += timedelta(days=1)
    with Lock(root.parent / "rest.lock"):
        with KeepAwake():
            ses = tr.Session(log=log)
            if a.codes:
                codes = [c.strip().zfill(6) for c in a.codes.split(",") if c.strip()]
            elif a.universe:
                import kis_universe as ku
                uni = ku.build_universe(ku.fetch_listing(), [], [], tier_a_size=0, cap_min_eok=a.cap_min, cap_max_eok=a.cap_max)
                codes = uni.tier_a + uni.tier_b
            elif a.all_listed:
                codes = sorted(s["symbol"] for mk in ("KOSPI", "KOSDAQ") for s in ses.stocks_all(mk))
            else:
                raise SystemExit("--codes, --universe 또는 --all-listed")
            log(f"종목 {len(codes)} × 종류 {len(kinds)} = {len(codes)*len(kinds)}건")
            t0 = time.time()
            heart = Heart(a.config, "flows", log=log); heart.beat("running", f"수급 시작 · {len(codes)}종목 × {len(kinds)}종")
            try:
                st = run(ses, root, codes, kinds, a.since or None, a.refresh, stop_at, heart)
            except Exception as exc:  # noqa: BLE001
                heart.end("error", f"수급 실패: {type(exc).__name__}"); raise
            line = f"토스 수급: 저장 {st['saved']}(빈 {st['empty']}, 오류 {st['errors']}), 행 {st['rows']:,}, 호출 {ses.calls}, 한도 초과 {ses.rate_hits}, {(time.time()-t0)/60:.0f}분"
            log(line); heart.end("done", f"수급 저장 {st['saved']:,}(빈 {st['empty']}, 오류 {st['errors']})")
            (root / "last_summary.json").write_text(json.dumps({"time": now_kst().isoformat(), **st, "calls": ses.calls}, ensure_ascii=False), encoding="utf-8")
            if st["saved"] > 200:
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
