"""첫 실행 점검 — 토큰 발급, 호가 단계 수, 1분봉·수급 보관 기간, 종목 수를 재 보고 값은 찍지 않는다(종목코드·건수만).

사용: python automations/toss_record/probe.py [--symbol 005930]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parents[1]))
import toss_rest as tr  # noqa: E402

DEFAULT_CFG = HERE.parents[1] / "ai-home" / "02_주식신호" / "config.yaml"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CFG))
    ap.add_argument("--symbol", default="005930")
    a = ap.parse_args()
    tr.load_secrets(a.config)
    ses = tr.Session()
    s = a.symbol
    ob = ses.orderbook(s)
    print(f"호가 {s}: 매도 {len(ob.get('asks', []))}단계, 매수 {len(ob.get('bids', []))}단계, 시각 {ob.get('timestamp')}")
    if ob.get("asks"):
        print(f"  매도1 {ob['asks'][0]}  매수1 {ob['bids'][0]}")
    px = ses.prices([s, "000660", "035720"])
    print(f"현재가 다건: {len(px)}건, 예 {px[0] if px else None}")
    tds = ses.trades(s, 50)
    print(f"최근 체결: {len(tds)}건, 예 {tds[0] if tds else None}")
    # 1분봉 보관: 최신 200봉, 그리고 2022-11-24 기준 이전 페이지
    d = ses.candles(s, "1m", 200)
    rows = d.get("candles") or []
    print(f"1분봉 최신 {len(rows)}봉: {rows[-1]['timestamp'] if rows else None} ~ {rows[0]['timestamp'] if rows else None}, nextBefore {d.get('nextBefore')}")
    old = ses.candles(s, "1m", 200, before="2022-11-24T09:05:00+09:00")
    orows = old.get("candles") or []
    print(f"1분봉 2022-11-24 이전: {len(orows)}봉, 가장 오래된 {orows[-1]['timestamp'] if orows else None}, nextBefore {old.get('nextBefore')}")
    older = ses.candles(s, "1m", 200, before="2022-11-22T09:05:00+09:00")
    print(f"1분봉 2022-11-22 이전: {len(older.get('candles') or [])}봉")
    dd = ses.candles(s, "1d", 200, before="2015-01-05T00:00:00+09:00")
    drows = dd.get("candles") or []
    print(f"일봉 2015-01-05 이전: {len(drows)}봉, 가장 오래된 {drows[-1]['timestamp'] if drows else None}")
    t0 = time.time()
    for kind in ("investor-trading", "program-trades", "short-selling", "credit-trades", "securities-lending"):
        try:
            recs = ses.daily_series_all(s, kind, max_calls=60)
            print(f"{kind}: {len(recs)}일, {recs[0]['date'] if recs else None} ~ {recs[-1]['date'] if recs else None}, 호출 누적 {ses.calls}")
        except tr.TossError as exc:
            print(f"{kind}: {exc}")
    print(f"수급 5종 {time.time()-t0:.0f}초")
    for mk in ("KOSPI", "KOSDAQ", "KR_ETC"):
        try:
            lst = ses.stocks_all(mk)
            print(f"종목 목록 {mk}: 보통주 STOCK {len(lst)}개")
        except tr.TossError as exc:
            print(f"종목 목록 {mk}: {exc}")
    print(f"호출 {ses.calls}, 한도 초과 {ses.rate_hits}, 재시도 {ses.retries}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
