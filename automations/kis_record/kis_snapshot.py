"""전 종목(또는 상위 N 종목) 호가 잔량 스냅샷 — REST 조회를 순서대로 돌며 10단계 호가·잔량·예상체결을 주기적으로 저장한다.

사용:
  python kis_snapshot.py --n 400 --until 15:35                 # 하루(작업 스케줄러 08:55)
  python kis_snapshot.py --codes 005930,000660 --sweeps 2       # 시험
- 웹소켓 등록 한도(3건)와 무관하다. 대신 조회 한도가 약 0.67건/초(실측, 1.5초 간격)라 전 종목 한 바퀴에 60분이 넘어 의미가 없다.
  그래서 대상을 '세력이 움직일 수 있는 크기'로 좁히고 두 층으로 나눈다(kis_universe.py):
    A층 = kis_watchlist + --candidates 파일(세력 흔적 후보) + 시총 범위 안 거래대금 상위 → --n 개(기본 150)를 **매 바퀴** 조회
    B층 = 시총 범위(--cap-min~--cap-max 억, 기본 300~5,000) 안 나머지 종목을 바퀴마다 남는 예산만큼 돌려 가며 조회(한 바퀴 = --cycle 초, 기본 300)
  기본값이면 바퀴당 200건: A층 150 + B층 50 → A층은 5분마다, B층(약 1,500)은 2시간 반에 한 번. 한도가 풀리면 --interval 을 줄이면 B층이 빨라진다.
  --plan 을 주면 대상만 세어 보여 주고 끝난다(KIS 호출·잠금 없음).
- 저장: %USERPROFILE%\\ai-office-data\\kis-record\\YYYY-MM-DD\\snap_HHMMSS\\book.csv (한 줄 = 종목 하나의 한 스냅샷: recv_ms·sweep·code + 71개 항목) → 끝나면 Parquet(전 열 문자열).
- 잠금(rest.lock, 분봉 수집과 공유)·절전 방지·요약(summary.json/safe_summary.json)·텔레그램 한 줄은 record.py 와 같다.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import kis_client as kc  # noqa: E402
import kis_rest as kr  # noqa: E402
import kis_universe as ku  # noqa: E402
from record import DEFAULT_CFG, DEFAULT_OUT, KeepAwake, Lock, csv_to_parquet, log, notify, now_kst, parse_until  # noqa: E402


def pick_universe(a) -> ku.Universe:
    """--codes 가 있으면 그 종목만 A층. 아니면 네이버 목록으로 시총 범위를 걸러 A층(매 바퀴)·B층(돌려 가며)을 만든다."""
    import kis_pick
    if a.codes:
        codes = [c.strip().zfill(6) for c in a.codes.split(",") if c.strip()]
        codes = [c for c in dict.fromkeys(codes) if kc.CODE_RE.match(c)]
        return ku.Universe(codes, [], {"A층": len(codes)})
    watch = kis_pick.watchlist(a.config)
    cands = ku.load_lines(a.candidates)
    try:
        listing = ku.fetch_listing()
    except Exception as exc:  # noqa: BLE001 — 네이버 목록이 안 오면 관심·후보만으로
        log(f"종목 목록 실패({type(exc).__name__}) — 관심 종목·후보만으로 진행")
        listing = []
    uni = ku.build_universe(listing, watch, cands, tier_a_size=a.n, cap_min_eok=a.cap_min, cap_max_eok=a.cap_max, price_min=a.price_min)
    if a.no_tier_b:
        uni = ku.Universe(uni.tier_a, [], {**uni.excluded, "B층": 0})
    return uni


class BookStore:
    def __init__(self, run_dir: Path):
        self.dir = run_dir; self.dir.mkdir(parents=True, exist_ok=True)
        self.f = None; self.w = None; self.n = 0; self.last_flush = time.time()

    def write(self, row: dict) -> None:
        if self.w is None:
            self.f = open(self.dir / "book.csv", "a", newline="", encoding="utf-8")
            self.w = csv.DictWriter(self.f, fieldnames=list(row.keys()), extrasaction="ignore")
            if self.f.tell() == 0:
                self.w.writeheader()
        self.w.writerow(row); self.n += 1
        if time.time() - self.last_flush > 5:
            self.f.flush(); self.last_flush = time.time()

    def close(self) -> None:
        if self.f:
            self.f.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CFG))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--codes", default="")
    ap.add_argument("--candidates", default="", help="한 줄에 코드 하나(세력 흔적 후보 등)")
    ap.add_argument("--n", type=int, default=150, help="A층(매 바퀴 조회) 크기")
    ap.add_argument("--cap-min", type=float, default=300, help="시가총액 하한(억)")
    ap.add_argument("--cap-max", type=float, default=5000, help="시가총액 상한(억) — 이보다 크면 세력이 못 움직인다고 보고 제외")
    ap.add_argument("--price-min", type=float, default=500, help="주가 하한(원)")
    ap.add_argument("--cycle", type=float, default=300, help="한 바퀴 목표 시간(초) — 이 안에 A층 전부 + B층 일부")
    ap.add_argument("--no-tier-b", action="store_true", help="B층 없이 A층만")
    ap.add_argument("--interval", type=float, default=1.5, help="조회 사이 최소 간격(초) — 실측 안전선 1.5")
    ap.add_argument("--until", default="15:35")
    ap.add_argument("--sweeps", type=int, default=0, help="N 바퀴만(시험용)")
    ap.add_argument("--no-parquet", action="store_true")
    ap.add_argument("--plan", action="store_true", help="대상만 세어 보여 주고 끝(KIS 호출 없음)")
    a = ap.parse_args()
    out = Path(a.out)
    if a.plan:
        uni = pick_universe(a)
        per = len(uni.sweep_plan(a.cycle, a.interval, 0))
        room = per - len(uni.tier_a)
        rot = len(uni.tier_b) / room * per * a.interval / 60 if room > 0 and uni.tier_b else 0
        log(f"대상: {uni.excluded} | 바퀴당 {per}건(A층 {len(uni.tier_a)} + B층 {room}), 간격 {a.interval}초 → 바퀴 {per*a.interval/60:.1f}분, B층 전부 한 번 도는 데 약 {rot:.0f}분")
        return 0
    with Lock(out / "rest.lock"):          # 분봉 수집과 같은 계좌 조회 한도를 쓰므로 REST 작업은 하나만
        return _run(a, out)


def _run(a, out: Path) -> int:
    kc.load_secrets(a.config)
    uni = pick_universe(a)
    if not uni.tier_a and not uni.tier_b:
        log("종목이 없어 종료"); return 3
    start = now_kst()
    until = parse_until(a.until)
    run_dir = out / start.strftime("%Y-%m-%d") / f"snap_{start:%H%M%S}"
    store = BookStore(run_dir)
    (run_dir / "codes.txt").write_text("\n".join(uni.tier_a), encoding="utf-8")
    (run_dir / "codes_tier_b.txt").write_text("\n".join(uni.tier_b), encoding="utf-8")
    per = len(uni.sweep_plan(a.cycle, a.interval, 0))
    log(f"대상 {uni.excluded} | 바퀴당 {per}건(A층 {len(uni.tier_a)} + B층 {per-len(uni.tier_a)}), 간격 {a.interval}초 → 바퀴 약 {per*a.interval/60:.1f}분, 종료 {until:%H:%M:%S}, 저장 {run_dir}")
    try:
        ses = kr.Session(interval=a.interval, log=log)
    except kr.KISError as exc:
        log(str(exc)); notify(a.config, f"호가 스냅샷 시작 실패: {exc}"); return 4
    sweeps, errors, empty = 0, {}, 0
    outcome = "정상"
    with KeepAwake():
        try:
            while a.sweeps == 0 and now_kst() < until or a.sweeps and sweeps < a.sweeps:
                sweeps += 1
                codes = uni.sweep_plan(a.cycle, a.interval, sweeps - 1)
                t0 = time.time(); ok = 0
                for c in codes:
                    if a.sweeps == 0 and now_kst() >= until:
                        break
                    try:
                        o = ses.asking_price(c)
                    except kr.KISError as exc:
                        k = str(exc)[:40]; errors[k] = errors.get(k, 0) + 1
                        continue
                    if not o or not o.get("askp1"):
                        empty += 1
                        continue
                    row = {"recv_ms": int(time.time() * 1000), "sweep": sweeps, "code": c}
                    row.update(o)
                    store.write(row); ok += 1
                log(f"바퀴 {sweeps}: {ok}/{len(codes)}개, {time.time()-t0:.0f}초, 누적 호출 {ses.calls} (한도 초과 {ses.rate_hits}회)")
        except KeyboardInterrupt:
            outcome = "키보드 중단"
        except OSError as exc:
            outcome = f"저장 오류: {type(exc).__name__}"
        finally:
            store.close()
    n_pq = 0
    if not a.no_parquet:
        n_pq, _ = csv_to_parquet(run_dir)
    summary = {"date": run_dir.parent.name, "run": run_dir.name, "outcome": outcome, "codes_n": len(uni.tier_a), "tier_b_n": len(uni.tier_b), "codes": uni.tier_a,
               "universe": uni.excluded, "cap_range_eok": [a.cap_min, a.cap_max], "sweeps": sweeps, "rows": store.n,
               "calls": ses.calls, "rate_hits": ses.rate_hits, "retries": ses.retries, "empty": empty, "errors": errors, "parquet_files": n_pq,
               "seconds": round((now_kst() - start).total_seconds())}
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    safe = {k: summary[k] for k in ("date", "run", "outcome", "codes_n", "sweeps", "rows", "calls", "rate_hits", "seconds")}
    (run_dir / "safe_summary.json").write_text(json.dumps(safe, ensure_ascii=False, indent=1), encoding="utf-8")
    line = f"호가 스냅샷 {run_dir.parent.name}: {outcome}, A층 {len(uni.tier_a)}·B층 {len(uni.tier_b)}종목, {sweeps}바퀴, 행 {store.n:,}, 한도 초과 {ses.rate_hits}회"
    log(line)
    if not a.sweeps:
        notify(a.config, line)
    return 0 if store.n else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        log(f"실패: {type(exc).__name__}: {str(exc)[:80]}")
        sys.exit(5)
