"""analyst_sources_kr — 야후 표기(코드.KS/.KQ)로 국내 종목을 받아 미국과 같은 raw 모양으로."""
import pytest

import analyst_sources_kr as k
import analyst_sources_us as us


class Spy:
    """fetch_raw 를 대신하는 가짜 — 부른 기호를 적고, fail 에 든 기호는 던진다."""
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def __call__(self, symbol, yf=None):
        self.calls.append(symbol)
        if symbol in self.fail:
            raise ValueError("가격 자료가 0일뿐")
        n = 250
        return {"t": symbol, "name": "Samsung Electronics", "exchange": "KSC", "sector": "Technology",
                "closes": [[f"d{i}", 1.0] for i in range(n)], "volumes": [1.0] * n}


@pytest.fixture
def spy(monkeypatch):
    s = Spy()
    monkeypatch.setattr(us, "fetch_raw", s)
    return s


def test_meta_exchange_is_used_with_one_call(spy):
    raw = k.fetch_raw_kr("005930", {"exch": "KS", "name": "삼성전자"})
    assert spy.calls == ["005930.KS"]
    assert raw["t"] == "005930" and raw["exchange"] == "코스피" and raw["currency"] == "KRW"
    assert raw["name_local"] == "삼성전자" and raw["name"] == "Samsung Electronics"


def test_kosdaq_meta(spy):
    raw = k.fetch_raw_kr("247540", {"exch": "KQ", "name": "에코프로비엠"})
    assert spy.calls == ["247540.KQ"] and raw["exchange"] == "코스닥"


def test_without_meta_tries_ks_then_kq(monkeypatch):
    s = Spy(fail={"247540.KS"}); monkeypatch.setattr(us, "fetch_raw", s)
    raw = k.fetch_raw_kr("247540", None)
    assert s.calls == ["247540.KS", "247540.KQ"] and raw["exchange"] == "코스닥" and raw["name_local"] is None


def test_both_fail_raises(monkeypatch):
    s = Spy(fail={"1.KS", "1.KQ"}); monkeypatch.setattr(us, "fetch_raw", s)
    with pytest.raises(ValueError):
        k.fetch_raw_kr("1", None)


def test_known_exchange_failure_is_not_retried_on_the_other(monkeypatch):
    s = Spy(fail={"005930.KS"}); monkeypatch.setattr(us, "fetch_raw", s)
    with pytest.raises(ValueError):
        k.fetch_raw_kr("005930", {"exch": "KS", "name": "삼성전자"})
    assert s.calls == ["005930.KS"]
