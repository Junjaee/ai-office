"""trade_poll — 가짜 세션으로 중복 제거·활발 종목 판정·전일 종가 고르기."""
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "kis_record"))
import trade_poll as tp  # noqa: E402
from live_board import LiveBoard, ts_ms  # noqa: E402


class FakeSes:
    def __init__(self, batches):
        self.batches = list(batches); self.calls = 0

    def trades(self, code, count=50):
        self.calls += 1
        return self.batches.pop(0) if self.batches else []

    def candles(self, code, interval, count=200, before=None, adjusted=None):
        return {"candles": [{"timestamp": "2026-09-29T00:00:00+09:00", "closePrice": "110", "highPrice": "112", "volume": "500"},
                            {"timestamp": "2026-09-26T00:00:00+09:00", "closePrice": "100", "highPrice": "104", "volume": "1000"}]}


def t(ts, p, v):
    return {"timestamp": f"2026-09-29T10:00:{ts:02d}.000+09:00", "price": str(p), "volume": str(v)}


def test_poll_one_dedupes_and_marks_hot():
    got = []
    ses = FakeSes([[t(5, 100, 1), t(4, 100, 2), t(3, 99, 1)], [t(7, 101, 5), t(6, 100, 1), t(5, 100, 1), t(4, 100, 2)]])
    poller = tp.TradePoller(ses, ["005930"], lambda ch, c, r: got.append(r), lambda m: None, threading.Event(), hot_threshold=2)
    assert poller.poll_one("005930") == 3           # 첫 조회는 전부(최근 10건 안)
    assert [r["timestamp"][17:19] for r in got] == ["03", "04", "05"], "시간순으로 넘긴다"
    assert poller.poll_one("005930") == 2           # 겹치는 2건은 빼고 새 2건만
    assert [r["price"] for r in got[3:]] == ["100", "101"]
    assert poller.hot["005930"] is True and poller.stats["new"] == 5


def test_daily_refs_skips_today_candle():
    from daily_ref import daily_refs
    r = daily_refs(FakeSes([]), ["005930"], log=lambda m: None)
    assert r["005930"]["prev_close"] == 100.0 and r["005930"]["days"] == 1 and r["005930"]["avg_amt5"] > 0


def test_board_money_fields():
    b = LiveBoard({"005930": "삼성전자"}, refs={"005930": {"prev_close": 100.0, "prev_high": 104.0, "high20": 110.0, "avg_amt5": 1e6, "avg_amt20": 7.8e7, "days": 20}})
    row = {"timestamp": "t"}
    for i in range(1, 11):
        row[f"ask{i}_p"] = str(105 + i); row[f"ask{i}_v"] = "10"; row[f"bid{i}_p"] = str(106 - i); row[f"bid{i}_v"] = "10"
    b.on_row("orderbook:kr", "005930", row)
    from live_board import now_iso
    b.on_row("trade:kr", "005930", {"timestamp": now_iso(), "price": "106", "volume": "20000"})   # 5분 거래대금 212만 = 평소 2.12배
    it = b.item("005930")
    assert it["pos"] == "전일 고가 돌파" and it["amt_ratio"] == 2.12 and it["chg_pct"] == 6.0 and it["mom15"] is None


def test_board_uses_trade_timestamp_and_chg():
    b = LiveBoard({"005930": "삼성전자"}, prev_close={"005930": 100.0})
    row = {"timestamp": "t"}
    for i in range(1, 11):
        row[f"ask{i}_p"] = str(100 + i); row[f"ask{i}_v"] = "10"; row[f"bid{i}_p"] = str(101 - i); row[f"bid{i}_v"] = "10"
    b.on_row("orderbook:kr", "005930", row)
    b.on_row("trade:kr", "005930", {"timestamp": "2020-01-01T09:00:00+09:00", "price": "101", "volume": "3"})   # 아주 옛날 체결 → 창 밖
    b.on_row("trade:kr", "005930", {"timestamp": "bad", "price": "101", "volume": "2"})                       # 시각 못 읽으면 지금
    it = b.item("005930")
    assert it["n_trades"] == 1 and it["chg_pct"] == 1.0 and it["prev_close"] == 100.0
    assert ts_ms("2026-09-29T10:07:15.007+09:00", 0) == 1790644035007
