"""토스증권 실시간 호가·체결 녹음기 — 연결 2개 × 100건으로 최대 100종목(호가+체결) 또는 200종목(호가만)을 하루 동안 저장한다.

사용:
  python automations/toss_record/record_toss.py --codes 005930,000660 --minutes 2          # 시험
  python automations/toss_record/record_toss.py --picks <파일> --until 15:35                 # 하루(한 줄에 코드 하나)
  python automations/toss_record/record_toss.py --auto --until 15:35                        # 후보 파일 + 시총 범위 안 거래대금 상위로 채움
- 저장: %USERPROFILE%\\ai-office-data\\toss-record\\YYYY-MM-DD\\run_HHMMSS\\{orderbook|trade}_<코드>.csv → 끝나면 Parquet(전 열 문자열). summary.json(로컬)·safe_summary.json(건수만).
- 잠금(ws.lock): 같은 클라이언트로 두 개를 돌리면 연결 한도(2개)를 서로 빼앗으므로 하나만. 절전 방지·텔레그램은 kis_record 와 같다.
- 자료는 본인 매매 목적만(제3자 배포 금지) — 원자료는 이 PC 에만 둔다.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1])); sys.path.insert(0, str(HERE.parent / "kis_record"))
import toss_rest as tr  # noqa: E402
import toss_ws as tw  # noqa: E402
from live_board import LiveBoard, LivePoster, live_settings, now_iso  # noqa: E402
from record import KeepAwake, Lock, csv_to_parquet, log, notify, now_kst, parse_until  # noqa: E402

LIVE_POST_SEC = 5.0

DEFAULT_CFG = HERE.parents[1] / "ai-home" / "02_주식신호" / "config.yaml"
DEFAULT_OUT = tr.DEFAULT_OUT
BOOK_COLS = ["recv_ms", "timestamp"] + [f"{s}{i}_{k}" for i in range(1, 11) for s in ("ask", "bid") for k in ("p", "v")] + ["ask_total", "bid_total", "levels"]
TRADE_COLS = ["recv_ms", "timestamp", "price", "volume"]


class Store:
    def __init__(self, run_dir: Path):
        self.dir = run_dir; self.dir.mkdir(parents=True, exist_ok=True)
        self.files: dict[tuple[str, str], tuple] = {}
        self.n = 0; self.last_flush = time.time()

    def write(self, channel: str, code: str, row: dict) -> None:
        kind = "orderbook" if channel.startswith("orderbook") else "trade"
        key = (kind, code)
        if key not in self.files:
            p = self.dir / f"{kind}_{code}.csv"; new = not p.exists()
            f = open(p, "a", newline="", encoding="utf-8")
            w = csv.DictWriter(f, fieldnames=BOOK_COLS if kind == "orderbook" else TRADE_COLS, extrasaction="ignore")
            if new:
                w.writeheader()
            self.files[key] = (f, w)
        row = {"recv_ms": int(time.time() * 1000), **row}
        self.files[key][1].writerow(row); self.n += 1
        if time.time() - self.last_flush > 5:
            for f, _ in self.files.values():
                f.flush()
            self.last_flush = time.time()

    def close(self) -> None:
        for f, _ in self.files.values():
            f.close()
        self.files = {}


def pick_codes(a) -> tuple[list[str], dict[str, str]]:
    """(종목 목록, 종목명 사전). 종목명은 네이버 목록에서(실시간 화면용, 실패해도 진행)."""
    import re
    import kis_universe as ku
    code_re = re.compile(r"^\d{6}$")
    listing: list[dict] = []
    try:
        listing = ku.fetch_listing()
    except Exception as exc:  # noqa: BLE001
        log(f"종목 목록 실패({type(exc).__name__}) — 종목명 없이 진행")
    names = {r["code"]: r["name"] for r in listing}
    if a.codes:
        codes = [c.strip().zfill(6) for c in a.codes.split(",") if c.strip()]
    elif a.picks:
        codes = [ln.strip() for ln in Path(a.picks).read_text(encoding="utf-8").splitlines() if code_re.match(ln.strip())]
    elif a.auto:
        cands = ku.load_lines(a.candidates)
        uni = ku.build_universe(listing, [], cands, tier_a_size=a.limit, cap_min_eok=a.cap_min, cap_max_eok=a.cap_max)
        codes = uni.tier_a
    else:
        raise SystemExit("--codes, --picks 또는 --auto")
    return [c for c in dict.fromkeys(codes) if code_re.match(c)][: a.limit], names


async def _record(a, codes: list[str], store: Store, until_dt, channels: tuple[str, ...], board: LiveBoard | None, poster: LivePoster | None) -> tuple[list[tw.ConnStats], str]:
    tr.load_secrets(a.config)
    ses = tr.Session(log=log)
    chunks = tw.split_codes(codes, len(channels))
    stats = [tw.ConnStats() for _ in chunks]
    started = now_iso()

    def until() -> bool:
        return now_kst() >= until_dt

    async def refresh():
        ses.token = ses._issue_token()

    def on_row(channel: str, code: str, row: dict) -> None:
        store.write(channel, code, row)
        if board is not None:
            board.on_row(channel, code, row)

    def meta() -> dict:
        return {"connections": sum(1 for s in stats if s.subscribed), "subscribed": sum(s.subscribed for s in stats), "reconnects": sum(s.reconnects for s in stats)}

    def summary_line() -> str:
        return f"{len(codes)}종목 · 호가 {sum(s.books for s in stats):,}·체결 {sum(s.trades for s in stats):,}행"

    tasks = [asyncio.create_task(tw.run_connection(lambda: ses.token, ch, channels, on_row, until, st, log, f"c{i+1}", refresh))
             for i, (ch, st) in enumerate(zip(chunks, stats))]
    last_report = time.time(); last_post = 0.0
    outcome = "정상"
    try:
        while not until() and any(not t.done() for t in tasks):
            await asyncio.sleep(1)
            if poster is not None and board is not None and time.time() - last_post >= LIVE_POST_SEC:
                last_post = time.time()
                b = board.board(codes, meta())
                await asyncio.to_thread(poster.post, "running", summary_line(), b, started)
            if time.time() - last_report >= 300:
                log(f"진행: 행 {store.n:,} (호가 {sum(s.books for s in stats):,}, 체결 {sum(s.trades for s in stats):,}), 재연결 {sum(s.reconnects for s in stats)}"
                    + (f", 전송 {poster.sent}/{poster.sent + poster.failed}" if poster else ""))
                last_report = time.time()
    except KeyboardInterrupt:
        outcome = "키보드 중단"
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    if poster is not None and board is not None:
        await asyncio.to_thread(poster.post, "done" if outcome == "정상" else "error", f"{outcome} · {summary_line()}", board.board(codes, meta()), started, now_iso())
    return stats, outcome


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CFG))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--codes", default="")
    ap.add_argument("--picks", default="")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--candidates", default="")
    ap.add_argument("--cap-min", type=float, default=300); ap.add_argument("--cap-max", type=float, default=5000)
    ap.add_argument("--mode", choices=["both", "book", "trade"], default="both")
    ap.add_argument("--limit", type=int, default=0, help="종목 상한(기본: 모드별 최대 100/200)")
    ap.add_argument("--minutes", type=float, default=0); ap.add_argument("--until", default="15:35")
    ap.add_argument("--no-parquet", action="store_true")
    ap.add_argument("--no-live", action="store_true", help="사이트(/api/live)로 실시간 자료를 보내지 않는다")
    a = ap.parse_args()
    channels = {"both": ("orderbook:kr", "trade:kr"), "book": ("orderbook:kr",), "trade": ("trade:kr",)}[a.mode]
    max_codes = tw.PER_CONN_LIMIT // len(channels) * tw.MAX_CONNECTIONS
    a.limit = min(a.limit or max_codes, max_codes)
    out = Path(a.out)
    with Lock(out / "ws.lock"):
        with KeepAwake():
            codes, names = pick_codes(a)
            if not codes:
                log("종목 없음"); return 3
            start = now_kst()
            until_dt = start.replace(microsecond=0) + __import__("datetime").timedelta(minutes=a.minutes) if a.minutes else parse_until(a.until)
            run_dir = out / start.strftime("%Y-%m-%d") / f"run_{start:%H%M%S}"
            store = Store(run_dir)
            (run_dir / "codes.txt").write_text("\n".join(codes), encoding="utf-8")
            live = None if a.no_live else live_settings(a.config)
            board = LiveBoard(names) if live else None
            poster = LivePoster(live[0], live[1], "home", "orderbook", "record", log) if live else None
            log(f"종목 {len(codes)}개 × 채널 {len(channels)} = 구독 {len(codes)*len(channels)}건(연결 {len(tw.split_codes(codes, len(channels)))}개), 종료 {until_dt:%H:%M:%S}, 저장 {run_dir}"
                + (", 실시간 전송 5초마다" if poster else ", 실시간 전송 없음(live_token 없음)"))
            try:
                stats, outcome = asyncio.run(_record(a, codes, store, until_dt, channels, board, poster))
            except tr.TossError as exc:
                log(str(exc)); notify(a.config, f"토스 녹음 시작 실패: {exc}"); return 4
            finally:
                store.close()
            n_pq = 0 if a.no_parquet else csv_to_parquet(run_dir)[0]
            summary = {"date": run_dir.parent.name, "run": run_dir.name, "outcome": outcome, "codes_n": len(codes), "codes": codes, "mode": a.mode, "rows": store.n,
                       "books": sum(s.books for s in stats), "trades": sum(s.trades for s in stats), "frames": sum(s.frames for s in stats),
                       "reconnects": sum(s.reconnects for s in stats), "errors": sum(s.errors for s in stats), "rejected": [r for s in stats for r in s.rejected],
                       "subscribed": sum(s.subscribed for s in stats), "parquet_files": n_pq, "seconds": round((now_kst() - start).total_seconds())}
            (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
            safe = {k: summary[k] for k in ("date", "run", "outcome", "codes_n", "mode", "rows", "books", "trades", "reconnects", "errors", "subscribed", "seconds")}
            (run_dir / "safe_summary.json").write_text(json.dumps(safe, ensure_ascii=False, indent=1), encoding="utf-8")
            if poster:
                summary["live_sent"] = poster.sent; summary["live_failed"] = poster.failed
            line = f"토스 녹음 {summary['date']}: {outcome}, {len(codes)}종목, 호가 {summary['books']:,}·체결 {summary['trades']:,}행, 재연결 {summary['reconnects']}, 거부 {len(summary['rejected'])}"
            log(line)
            if not a.minutes:
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
