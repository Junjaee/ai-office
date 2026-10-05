"""run_analyst — 수집·계산·저장 흐름(가짜 수집기·가짜 사이트)과 공개 기록 규칙."""
import logging
import sys
import types
import warnings

import pytest

import analyst_publish
import run_analyst as mod
from test_analyst_metrics import make_raw


class FakeSite:
    def __init__(self, watch):
        self._watch = watch; self.sent = []

    def watch(self, market):
        return list(self._watch)

    def ingest(self, market, kind, doc, ticker=None):
        self.sent.append((market, kind, ticker, doc))


def args(dry=False):
    return types.SimpleNamespace(dry_run=dry, market="us")


def cfg(tmp_path, tickers="AAA\nBBB\n# 주석\n\nCCC\n"):
    u = tmp_path / "u.txt"; u.write_text(tickers, encoding="utf-8")
    return {"universe_us": str(u), "max_fail_ratio": 0.2, "request_delay": 0}


def fetch_ok(t):
    return make_raw(t=t, name=f"{t} Corp")


def test_collects_universe_plus_watch_and_publishes(tmp_path):
    site = FakeSite(["ZZZ", "AAA"])
    out = mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch_ok, site=site)
    assert out["counts"] == {"checked": 4, "watch": 2, "failed": 0, "failed_watch": 0}
    kinds = [(k, t) for _, k, t, _ in site.sent]
    assert kinds[0] == ("board", None) and sorted(t for k, t in kinds[1:]) == ["AAA", "BBB", "CCC", "ZZZ"]
    board = site.sent[0][3]
    assert board["market"] == "us" and len(board["rows"]) == 4
    assert board["as_of"] == make_raw()["closes"][-1][0]
    doc = next(d for _, k, t, d in site.sent if t == "ZZZ")
    assert set(doc) == {"market", "as_of", "rec", "checks", "diag", "peers", "ref"} and len(doc["checks"]) == 7


def test_public_outputs_never_name_tickers(tmp_path):
    out = mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch_ok, site=FakeSite(["ZZZ"]))
    text = " ".join(out["lines"]) + " ".join(v[1] for v in out["tasks"].values()) + mod.build_summary(out["counts"], 3)
    for t in ("AAA", "BBB", "CCC", "ZZZ"):
        assert t not in text
    assert "점검 4건" in mod.build_summary(out["counts"], 3)


def test_some_failures_are_counted_but_too_many_abort(tmp_path):
    def flaky(t):
        if t == "BBB":
            raise ValueError("막힘")
        return fetch_ok(t)
    site = FakeSite([])
    out = mod.do_work(cfg(tmp_path, "AAA\nBBB\nCCC\nDDD\nEEE\nFFF\n"), args(), lambda m: None, fetch=flaky, site=site)
    assert out["counts"]["failed"] == 1 and out["counts"]["checked"] == 5

    def dead(t):
        raise ValueError("막힘")
    site2 = FakeSite([])
    with pytest.raises(RuntimeError):
        mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=dead, site=site2)
    assert site2.sent == []                     # 실패가 많으면 지난 자료를 덮어쓰지 않는다


def test_dead_watch_tickers_do_not_abort_and_are_listed_as_missing(tmp_path):
    dead = [f"W{i:02d}" for i in range(25)]

    def fetch(t):
        if t in dead:
            raise ValueError("없는 종목")
        return fetch_ok(t)
    site = FakeSite(dead)
    out = mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch, site=site)
    assert out["counts"] == {"checked": 3, "watch": 25, "failed": 25, "failed_watch": 25}
    board = site.sent[0][3]
    assert board["missing"] == dead and len(board["rows"]) == 3


def test_reference_set_ignores_watch_only_tickers(tmp_path):
    def fetch(t):
        raw = make_raw(t=t, name=f"{t} Corp")
        if t == "ZZZ":
            raw["sector"] = "Other"
        return raw
    site = FakeSite(["ZZZ"])
    mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch, site=site)
    med = site.sent[0][3]["medians"]
    assert "Other" not in med["sector"]
    doc = next(d for _, k, t, d in site.sent if t == "AAA")
    assert all(p["t"] != "ZZZ" for p in doc["peers"])


def test_fetch_noise_never_reaches_public_logs(tmp_path, capsys, caplog):
    def noisy(t):
        print(t)
        print(t, file=sys.stderr)
        warnings.warn(t)
        logging.getLogger("yfinance").error(t)
        raise ValueError(t)
    caplog.set_level(logging.DEBUG)
    with pytest.raises(RuntimeError):
        mod.do_work(cfg(tmp_path), args(), print, fetch=noisy, site=FakeSite(["ZZZ"]))
    cap = capsys.readouterr()
    everything = cap.out + cap.err + caplog.text
    for t in ("AAA", "BBB", "CCC", "ZZZ"):
        assert t not in everything
    assert "수집 실패 1건" in cap.out


def test_watch_read_failure_is_tolerated_only_in_dry_run(tmp_path):
    class Down(FakeSite):
        def watch(self, market):
            raise OSError("사이트에 아직 경로가 없음")
    out = mod.do_work(cfg(tmp_path), args(dry=True), lambda m: None, fetch=fetch_ok, site=Down([]))
    assert out["counts"] == {"checked": 3, "watch": 0, "failed": 0, "failed_watch": 0}
    with pytest.raises(OSError):
        mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch_ok, site=Down([]))


def test_dry_run_sends_nothing(tmp_path):
    site = FakeSite(["ZZZ"])
    out = mod.do_work(cfg(tmp_path), args(dry=True), lambda m: None, fetch=fetch_ok, site=site)
    assert site.sent == [] and out["counts"]["checked"] == 4


def test_site_client_urls_and_token():
    calls = []

    class Http:
        def get(self, url, params=None, timeout=None):
            calls.append(("GET", url, params, None))
            return types.SimpleNamespace(status_code=200, json=lambda: {"watch": ["NVDA"]}, raise_for_status=lambda: None)

        def post(self, url, json=None, headers=None, timeout=None):
            calls.append(("POST", url, json, headers))
            return types.SimpleNamespace(status_code=200, json=lambda: {"ok": True}, raise_for_status=lambda: None)

    s = analyst_publish.Site("https://x.example/", token="tok", http=Http())
    assert s.watch("us") == ["NVDA"]
    s.ingest("us", "ticker", {"a": 1}, ticker="ORCL")
    assert calls[0] == ("GET", "https://x.example/api/stock", {"market": "us", "view": "watch"}, None)
    assert calls[1] == ("POST", "https://x.example/api/stock/ingest", {"market": "us", "kind": "ticker", "doc": {"a": 1}, "ticker": "ORCL"}, {"X-Live-Token": "tok"})
    assert analyst_publish.Site("https://x.example", http=Http())._headers() == {}
