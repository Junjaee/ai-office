"""토스 모듈 — 네트워크 없는 시험(가짜 HTTP 로 토큰·페이지 넘김, 구독 선언·분할, 호가 평탄화, 분봉 열 변환, 수급 평탄화)."""
import json
import os
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "kis_record"))
import toss_rest as tr  # noqa: E402
import toss_ws as tw  # noqa: E402
import toss_candles as tc  # noqa: E402
import toss_flows as tf  # noqa: E402


class FakeResp:
    def __init__(self, status, body, headers=None):
        self.status_code = status; self._body = body; self.headers = headers or {}

    def json(self):
        return self._body


class FakeHttp:
    def __init__(self, script):
        self.script = list(script); self.calls = []

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw.get("data")))
        return FakeResp(200, {"access_token": "tok-" + str(len(self.calls)), "expires_in": 86400})

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append(("GET", url, params))
        fn = self.script.pop(0)
        return fn(url, params)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TOSS_CLIENT_ID", "id-1234567890abcdef"); monkeypatch.setenv("TOSS_CLIENT_SECRET", "s" * 30)
    return tmp_path / "token.json"


def test_token_cached_and_shared(env):
    http = FakeHttp([])
    s1 = tr.Session(log=lambda m: None, token_file=env, http=http)
    assert s1.token == "tok-1" and json.loads(env.read_text())["access_token"] == "tok-1"
    s2 = tr.Session(log=lambda m: None, token_file=env, http=FakeHttp([]))
    assert s2.token == "tok-1"                     # 파일 공유 — 재발급하지 않는다(재발급하면 s1 토큰이 무효가 되므로)
    env.write_text(json.dumps({"access_token": "tok-x", "expires_at": time.time() + 3600}))
    assert s1._issue_token() == "tok-x"            # 다른 프로세스가 먼저 갱신했으면 그것을 쓴다


def test_get_handles_429_and_401(env):
    script = [
        lambda u, p: FakeResp(429, {"error": {"code": "rate"}}, {"Retry-After": "0"}),
        lambda u, p: FakeResp(401, {"error": {"code": "token-revoked"}}),
        lambda u, p: FakeResp(200, {"result": {"asks": [], "bids": []}}, {"X-RateLimit-Remaining": "5"}),
    ]
    http = FakeHttp(script)
    s = tr.Session(log=lambda m: None, token_file=env, http=http)
    tr.GROUP_RATE["MARKET_DATA"] = 1000
    r = s.get("/api/v1/orderbook", {"symbol": "005930"})
    assert r == {"asks": [], "bids": []} and s.rate_hits == 1 and s.retries == 2
    assert [c[0] for c in http.calls].count("POST") == 2        # 401 뒤 재발급 1회
    with pytest.raises(tr.TossError):
        http.script = [lambda u, p: FakeResp(404, {"error": {"code": "stock-not-found"}})]
        s.get("/api/v1/orderbook", {"symbol": "000000"})


def test_candles_all_pages_and_since(env):
    def page(before_ts, rows):
        return lambda u, p: FakeResp(200, {"result": {"candles": rows, "nextBefore": before_ts}}, {"X-RateLimit-Remaining": "9"})
    rows1 = [{"timestamp": "2026-09-29T09:03:00+09:00", "closePrice": "3"}, {"timestamp": "2026-09-29T09:02:00+09:00", "closePrice": "2"}]
    rows2 = [{"timestamp": "2026-09-29T09:01:00+09:00", "closePrice": "1"}, {"timestamp": "2026-09-26T15:30:00+09:00", "closePrice": "0"}]
    http = FakeHttp([page("2026-09-29T09:01:00+09:00", rows1), page("x", rows2), page(None, [])])
    s = tr.Session(log=lambda m: None, token_file=env, http=http)
    tr.GROUP_RATE["MARKET_DATA_CHART"] = 1000
    out = s.candles_all("005930", since="2026-09-29")
    assert [r["closePrice"] for r in out] == ["1", "2", "3"]     # 오래된 → 최신, since 앞은 버림
    assert len([c for c in http.calls if c[0] == "GET"]) == 2    # since 를 지나면 더 부르지 않는다


def test_daily_series_all_dedup(env):
    p1 = lambda u, p: FakeResp(200, {"result": {"records": [{"date": "2026-09-29"}, {"date": "2026-09-26"}], "nextUntil": "2026-09-25"}})
    p2 = lambda u, p: FakeResp(200, {"result": {"records": [{"date": "2026-09-26"}, {"date": "2026-09-25"}], "nextUntil": None}})
    s = tr.Session(log=lambda m: None, token_file=env, http=FakeHttp([p1, p2]))
    tr.GROUP_RATE["MARKET_DATA"] = 1000
    out = s.daily_series_all("005930", "investor-trading")
    assert [r["date"] for r in out] == ["2026-09-25", "2026-09-26", "2026-09-29"]


def test_declaration_and_split():
    d = tw.declaration(["005930", "000660"], ("orderbook:kr", "trade:kr"))
    assert d[0] == {"id": "rec-1"} and d[1]["type"] == "orderbook:kr" and d[2]["codes"] == ["005930", "000660"]
    with pytest.raises(ValueError):
        tw.declaration([f"{i:06d}" for i in range(51)], ("orderbook:kr", "trade:kr"))
    codes = [f"{i:06d}" for i in range(130)]
    chunks = tw.split_codes(codes, 2)
    assert [len(c) for c in chunks] == [50, 50]                  # 연결 2개 × 50종목(둘 다)까지만
    assert [len(c) for c in tw.split_codes(codes, 1)] == [100, 30]


def test_flatten_book():
    data = {"timestamp": "t", "asks": [{"price": "101", "volume": "5"}, {"price": "102", "volume": "7"}], "bids": [{"price": "100", "volume": "3"}]}
    row = tw.flatten_book(data)
    assert row["ask1_p"] == "101" and row["bid1_v"] == "3" and row["ask3_p"] == "" and row["ask_total"] == "12" and row["bid_total"] == "3" and row["levels"] == "2/1"


def test_to_kis_rows_regular_only():
    candles = [
        {"timestamp": "2026-09-29T09:01:00.000+09:00", "openPrice": "1", "highPrice": "2", "lowPrice": "0", "closePrice": "1", "volume": "10"},
        {"timestamp": "2026-09-29T15:31:00.000+09:00", "openPrice": "1", "highPrice": "2", "lowPrice": "0", "closePrice": "1", "volume": "20"},
        {"timestamp": "2026-09-29T15:32:00.000+09:00", "openPrice": "1", "highPrice": "2", "lowPrice": "0", "closePrice": "1", "volume": "30"},   # 애프터마켓
        {"timestamp": "2026-09-29T08:31:00.000+09:00", "openPrice": "1", "highPrice": "2", "lowPrice": "0", "closePrice": "1", "volume": "40"},   # 프리마켓
    ]
    by_day = tc.to_kis_rows(candles)
    rows = by_day["20260929"]
    assert [r["stck_cntg_hour"] for r in rows] == ["090000", "153000"]      # 봉 시작 시각으로 변환, 정규장만
    assert tc.to_kis_rows(candles, regular_only=False)["20260929"][0]["stck_cntg_hour"] == "083000"


def test_flatten_flows():
    rec = {"date": "2026-09-29", "individual": None, "institution": {"netBuyVolume": "5", "breakdown": {"pension": {"netBuyVolume": "1"}}}, "tags": ["a"]}
    f = tf.flatten(rec)
    assert f["individual"] == "" and f["institution.breakdown.pension.netBuyVolume"] == "1" and f["tags"] == '["a"]'


def test_load_secrets_rejects_placeholder(tmp_path):
    cfg = tmp_path / "c.yaml"; cfg.write_text("toss_client_id: 여기에\ntoss_client_secret: x\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        tr.load_secrets(cfg)
    cfg.write_text("toss_client_id: abcdefghijklmnop1234\ntoss_client_secret: " + "y" * 40 + "\n", encoding="utf-8")
    tr.load_secrets(cfg)
    assert os.environ["TOSS_CLIENT_ID"].startswith("abcdef")
