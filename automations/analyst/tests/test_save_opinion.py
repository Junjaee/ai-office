"""save_opinion — 해석 JSON 을 사이트 자료로 채워 저장하는 스크립트(가짜 Site)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analyst_publish  # noqa: E402
import save_opinion as mod  # noqa: E402

OP = {"verdict": "클라우드 매출이 빠르게 늘고 있다.",
      "good": [{"text": "매출 증가세가 이어진다.", "src": "재무"}],
      "bad": [{"text": "부채가 많다.", "src": "재무"}],
      "watch": ["다음 실적에서 클라우드 매출을 본다."]}
KEYS = {"price", "as_of", "next_earn", "verdict", "good", "bad", "watch"}


class FakeSite:
    def __init__(self, doc="default", fail=None):
        self.doc = {"as_of": "2026-10-02", "rec": {"price": 142.3, "next_earn": "2026-12-10"}} if doc == "default" else doc
        self.saved, self.fail = [], fail

    def ticker(self, market, ticker):
        return {"market": market, "ticker": ticker, "doc": self.doc}

    def opinion(self, market, ticker, opinion):
        if self.fail:
            raise self.fail
        self.saved.append((market, ticker, opinion))
        return "2026-10-06T09:12:33.000Z"


def write(tmp_path, data):
    p = tmp_path / "op.json"
    p.write_text(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_check_text_finds_forbidden_sentences():
    assert mod.check_text(OP) == []
    bad = dict(OP, verdict="좋은 회사다. 지금은 매수 추천 구간이다.", watch=["목표가 200달러", "실적을 본다"])
    found = mod.check_text(bad)
    assert any("매수 추천" in s for s in found) and any("목표가" in s for s in found)
    assert not any("좋은 회사다" in s for s in found) and not any("실적을 본다" in s for s in found)
    assert mod.check_text(dict(OP, good=[{"text": "비중  확대 가능", "src": "재무"}]))   # 공백 차이도 잡는다


def test_saves_with_site_data(tmp_path, capsys):
    site = FakeSite()
    assert mod.main(["us", "orcl", "--file", write(tmp_path, OP)], site=site) == 0
    market, ticker, op = site.saved[0]
    assert (market, ticker) == ("us", "ORCL")
    assert set(op) == KEYS
    assert (op["price"], op["as_of"], op["next_earn"]) == (142.3, "2026-10-02", "2026-12-10")
    assert op["verdict"] == OP["verdict"] and op["good"] == OP["good"]
    out = capsys.readouterr().out
    assert "2026-10-06T09:12:33.000Z" in out and "/home/stock/us/ORCL" in out


def test_extra_keys_dropped_watch_defaults_and_next_earn_none(tmp_path):
    site = FakeSite(doc={"as_of": "2026-10-02", "rec": {"price": 10}})
    data = {k: v for k, v in OP.items() if k != "watch"} | {"rating": "A", "id": "x"}
    assert mod.main(["us", "ORCL", "--file", write(tmp_path, data)], site=site) == 0
    op = site.saved[0][2]
    assert op["watch"] == [] and op["next_earn"] is None and set(op) == KEYS


def test_no_stock_data_exits_1(tmp_path, capsys):
    for doc in (None, {"as_of": "2026-10-02", "rec": {}}):
        site = FakeSite(doc=doc)
        assert mod.main(["us", "ORCL", "--file", write(tmp_path, OP)], site=site) == 1
        assert site.saved == []
    assert capsys.readouterr().err


def test_forbidden_words_exit_2_and_not_saved(tmp_path, capsys):
    site = FakeSite()
    assert mod.main(["us", "ORCL", "--file", write(tmp_path, dict(OP, verdict="강력 매수 의견이다."))], site=site) == 2
    assert site.saved == [] and "강력 매수" in capsys.readouterr().err


@pytest.mark.parametrize("data", ["{not json", "[1]", {"good": OP["good"], "bad": OP["bad"]},
                                  dict(OP, good=[]), dict(OP, bad=None), dict(OP, verdict="  ")])
def test_bad_file_exits_1(tmp_path, data):
    site = FakeSite()
    assert mod.main(["us", "ORCL", "--file", write(tmp_path, data)], site=site) == 1
    assert site.saved == []


def test_missing_file_exits_1(tmp_path):
    assert mod.main(["us", "ORCL", "--file", str(tmp_path / "nope.json")], site=FakeSite()) == 1


def test_http_failure_exits_1(tmp_path, capsys):
    assert mod.main(["us", "ORCL", "--file", write(tmp_path, OP)], site=FakeSite(fail=RuntimeError("HTTP 400"))) == 1
    assert "HTTP 400" in capsys.readouterr().err


# --- Site 클라이언트 ---

class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Http:
    def __init__(self, *posts):
        self.calls, self.posts = [], list(posts)

    def get(self, url, params=None, timeout=None):
        self.calls.append(("GET", url, params))
        return Resp(200 if params.get("ticker") != "NONE" else 500, {"market": "us", "view": params.get("view"), "doc": None})

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("POST", url, json, headers))
        return self.posts.pop(0)


def test_site_get_view_ticker_and_opinion():
    http = Http(Resp(200, {"ok": True, "id": "ID1"}))
    s = analyst_publish.Site("https://x.example/", token="tok", http=http)
    assert s.get_view("us", "index")["view"] == "index"
    assert s.ticker("us", "ORCL")["doc"] is None
    assert s.opinion("us", "ORCL", {"verdict": "v"}) == "ID1"
    assert http.calls[0] == ("GET", "https://x.example/api/stock", {"market": "us", "view": "index"})
    assert http.calls[1] == ("GET", "https://x.example/api/stock", {"market": "us", "ticker": "ORCL"})
    assert http.calls[2] == ("POST", "https://x.example/api/stock/opinion",
                             {"market": "us", "ticker": "ORCL", "opinion": {"verdict": "v"}}, {"X-Live-Token": "tok"})
    with pytest.raises(RuntimeError):
        s.ticker("us", "NONE")


def test_site_opinion_retries_once_on_5xx_and_not_on_4xx():
    waits = []
    s = analyst_publish.Site("https://x.example", http=Http(Resp(503, {}), Resp(200, {"id": "ID2"})), sleep=waits.append)
    assert s.opinion("us", "ORCL", {}) == "ID2" and waits == [2]
    s = analyst_publish.Site("https://x.example", http=Http(Resp(400, {}), Resp(200, {"id": "X"})), sleep=waits.append)
    with pytest.raises(RuntimeError):
        s.opinion("us", "ORCL", {})
    assert len(s.http.calls) == 1
