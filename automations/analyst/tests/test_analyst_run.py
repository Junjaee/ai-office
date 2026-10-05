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
    def __init__(self, watch, history=None):
        self._watch = watch; self.sent = []; self.order = []; self.extra = {}; self._history = history

    def watch(self, market):
        return list(self._watch)

    def get_view(self, market, view):
        assert view == "lenshist"
        return {"market": market, "history": self._history}

    def ingest(self, market, kind, doc, ticker=None, date=None):
        self.order.append(kind)
        if kind in ("index", "lenshist"):   # 3단계에 더해진 종류 — 앞 단계 시험이 보는 sent 목록은 그대로 둔다
            self.extra[kind] = doc
            return
        self.sent.append((market, kind, ticker, doc))
        self.dates = getattr(self, "dates", []) + [(kind, date)]

    @property
    def docs(self):
        """보낸 문서를 이름으로: board · lens:<날짜> · ticker:<기호>."""
        names = {"board": lambda t, d: "board", "lens": lambda t, d: f"lens:{d['date']}", "ticker": lambda t, d: f"ticker:{t}"}
        return {names[k](t, d): d for _, k, t, d in self.sent}


@pytest.fixture(autouse=True)
def no_sec_ua(monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)   # 시험이 실제 EDGAR 를 부르지 않게


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
    assert {k: v for k, v in out["counts"].items() if k not in ("candidates", "news")} == {"checked": 4, "watch": 2, "failed": 0, "failed_watch": 0}
    kinds = [(k, t) for _, k, t, _ in site.sent]
    assert kinds[-2:] == [("board", None), ("lens", None)] and sorted(t for k, t in kinds[:-2]) == ["AAA", "BBB", "CCC", "ZZZ"]   # 종목 자료가 먼저
    assert site.dates[-1] == ("lens", make_raw()["closes"][-1][0])
    board = site.docs["board"]
    assert board["market"] == "us" and len(board["rows"]) == 4
    assert board["as_of"] == make_raw()["closes"][-1][0]
    doc = next(d for _, k, t, d in site.sent if t == "ZZZ")
    assert set(doc) == {"market", "as_of", "rec", "checks", "diag", "peers", "ref", "lenses", "events", "news"} and len(doc["checks"]) == 7


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
    assert out["counts"]["failed_watch"] == 25 and out["counts"]["checked"] == 3
    board = site.docs["board"]
    assert board["missing"] == dead and len(board["rows"]) == 3


def test_reference_set_ignores_watch_only_tickers(tmp_path):
    def fetch(t):
        raw = make_raw(t=t, name=f"{t} Corp")
        if t == "ZZZ":
            raw["sector"] = "Other"
        return raw
    site = FakeSite(["ZZZ"])
    mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch, site=site)
    med = site.docs["board"]["medians"]
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
    assert out["counts"]["checked"] == 3 and out["counts"]["watch"] == 0
    with pytest.raises(OSError):
        mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch_ok, site=Down([]))


def test_dry_run_sends_nothing(tmp_path):
    site = FakeSite(["ZZZ"])
    out = mod.do_work(cfg(tmp_path), args(dry=True), lambda m: None, fetch=fetch_ok, site=site)
    assert site.sent == [] and out["counts"]["checked"] == 4


AS_OF = make_raw()["closes"][-1][0]


def fetch_info(extra):
    """조용한 종목(거래량 일정·성장 자료 없음)에 종목별로 info 를 덮어쓴다."""
    def fetch(t):
        raw = make_raw(t=t, name=f"{t} Corp", volumes=[1000] * 250)
        raw["info"] = {"forwardPE": None, "trailingPE": None, "priceToBook": None, **(extra.get(t) or {})}
        return raw
    return fetch


def test_lenses_reach_board_docs_and_lens_log(tmp_path):
    # AAA 는 매출 +30%·이익 +10% → 실적 개선. BBB 는 최근 공시 → 사건. CCC 는 아무 데도 안 걸린다.
    site = FakeSite([])

    def filings_for(t, since):
        return [{"form": "8-K", "date": AS_OF, "items": "2.02"}] if t == "BBB" else []
    out = mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch_info({"AAA": {"revenueGrowth": 0.30, "earningsGrowth": 0.10}}),
                      site=site, filings_for=filings_for)
    board = site.docs["board"]
    by = {r["t"]: [x["id"] for x in r["lenses"]] for r in board["rows"]}
    assert by == {"AAA": ["growth"], "BBB": ["event"], "CCC": []}
    assert list(board["lens_info"]) == ["value", "growth", "event", "flow"]
    assert site.docs["ticker:BBB"]["events"] == [{"date": AS_OF, "kind": "실적 발표"}]
    assert [x["id"] for x in site.docs["ticker:AAA"]["lenses"]] == by["AAA"]
    log = site.docs[f"lens:{AS_OF}"]
    assert log["date"] == AS_OF and [h["t"] for h in log["hits"]["event"]] == ["BBB"] and log["hits"]["flow"] == []
    assert log["hits"]["growth"][0]["close"] == site.docs["ticker:AAA"]["rec"]["price"]
    assert log["index"] == {"t": "SPY", "close": 150.0}
    assert out["counts"]["candidates"] == 2 and out["tasks"]["discover"][0] is True
    assert "후보 2종목" in out["tasks"]["discover"][1] and "AAA" not in out["tasks"]["discover"][1]


def test_lens_log_and_candidates_cover_fresh_reference_universe_only(tmp_path):
    def fetch(t):
        raw = fetch_info({})(t)
        if t == "BBB":                                   # 기준 묶음이지만 자료가 기준일보다 오래됐다
            raw["closes"][-1][0] = "2025-01-01"
        return raw
    site = FakeSite(["ZZZ"])                             # ZZZ 는 관심만
    out = mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch, site=site, filings_for=lambda t, since: [{"form": "8-K", "date": AS_OF, "items": "2.02"}])
    by = {r["t"]: [x["id"] for x in r["lenses"]] for r in site.docs["board"]["rows"]}
    assert by == {"AAA": ["event"], "BBB": [], "CCC": ["event"], "ZZZ": []}            # 관점은 기준 묶음의 그날 자료만
    assert site.docs["ticker:ZZZ"]["lenses"] == [] and site.docs["ticker:ZZZ"]["events"]   # 공시는 남는다
    log = site.docs[f"lens:{AS_OF}"]
    assert sorted(h["t"] for h in log["hits"]["event"]) == ["AAA", "CCC"]
    assert out["counts"]["candidates"] == 2 and "후보 2종목" in out["tasks"]["discover"][1]


def test_watch_only_later_date_does_not_move_as_of_and_universe_is_on_board(tmp_path):
    def fetch(t):
        raw = fetch_info({"ZZZ": {"revenueGrowth": 0.30, "earningsGrowth": 0.10}})(t)   # ZZZ 는 기준 묶음이면 실적 개선에 걸릴 종목
        if t == "ZZZ":
            raw["closes"][-1][0] = "2099-01-01"
        return raw
    site = FakeSite(["ZZZ"])
    mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch, site=site)
    board = site.docs["board"]
    assert board["as_of"] == AS_OF and board["universe"] == 3
    assert next(r for r in board["rows"] if r["t"] == "ZZZ")["lenses"] == []


def test_filings_failure_is_counted_not_fatal_and_never_named(tmp_path, capsys):
    site = FakeSite([])

    def filings_for(t, since):
        raise RuntimeError(f"403 for https://data.sec.gov/CIK{t}.json")
    out = mod.do_work(cfg(tmp_path), args(), print, fetch=fetch_info({}), site=site, filings_for=filings_for)
    cap = capsys.readouterr()
    text = cap.out + cap.err
    assert "AAA" not in text and "BBB" not in text and "403" not in text and "sec.gov" not in text
    assert "공시를 받지 못해 건너뛴 종목 3건" in text
    assert site.docs["board"]["rows"] and out["counts"]["checked"] == 3
    assert site.docs["ticker:AAA"]["events"] == []


def test_filings_stop_asking_after_ten_straight_failures(tmp_path, capsys):
    asked = []

    def filings_for(t, since):
        asked.append(t)
        if t == "T00":
            return []
        raise RuntimeError("막힘")
    site = FakeSite([])
    mod.do_work(cfg(tmp_path, "\n".join(f"T{i:02d}" for i in range(20))), args(), print, fetch=fetch_info({}), site=site, filings_for=filings_for)
    text = capsys.readouterr().out
    assert len(asked) == 11 and text.count("공시를 받지 못해") == 1      # 성공 1번 뒤 연달아 10번 실패
    assert site.docs["board"]["filings_ok"] is False


def test_filings_breaker_counts_consecutive_failures_only(tmp_path, capsys):
    asked = []

    def filings_for(t, since):
        asked.append(t)
        if t != "T00":
            raise RuntimeError("막힘")
        return []
    site = FakeSite([])
    mod.do_work(cfg(tmp_path, "\n".join(f"T{i:02d}" for i in range(7))), args(), print, fetch=fetch_info({}), site=site, filings_for=filings_for)
    text = capsys.readouterr().out
    assert len(asked) == 7 and "공시를 받지 못해 건너뛴 종목 6건" in text
    assert site.docs["board"]["filings_ok"] is False


def test_success_resets_the_failure_streak(tmp_path):
    asked = []

    def filings_for(t, since):
        asked.append(t)
        if int(t[1:]) % 10 == 9:       # 9번째마다 성공 — 9번 실패 뒤 성공이라 끊기지 않는다
            return []
        raise RuntimeError("막힘")
    mod.do_work(cfg(tmp_path, "\n".join(f"T{i:02d}" for i in range(30))), args(), lambda m: None, fetch=fetch_info({}), site=FakeSite([]), filings_for=filings_for)
    assert len(asked) == 30


def test_filings_ok_only_when_configured_and_complete(tmp_path):
    site = FakeSite([])
    mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch_info({}), site=site, filings_for=lambda t, since: [])
    board = site.docs["board"]
    assert board["filings_ok"] is True and "확인하지 못해" not in board["lens_info"]["event"]["rule"]
    site = FakeSite([])
    mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch_info({}), site=site)   # SEC_USER_AGENT 없음
    board = site.docs["board"]
    assert board["filings_ok"] is False and board["lens_info"]["event"]["rule"].endswith("(오늘은 공시를 확인하지 못해 가격 조건만 봤습니다)")


def test_lens_counts_are_progressed_for_dry_run(tmp_path):
    lines = []
    mod.do_work(cfg(tmp_path), args(dry=True), lines.append, fetch=fetch_info({}), site=FakeSite([]))
    assert any(l.startswith("후보 ") and "싸고 탄탄" in l and "AAA" not in l for l in lines)


def test_filings_loop_stops_when_time_budget_is_spent(tmp_path, capsys):
    asked = []

    def filings_for(t, since):
        asked.append(t)
        return []
    ticks = iter(range(0, 10_000, 100))          # 가짜 시계: 부를 때마다 100초씩 간다
    c = cfg(tmp_path, "\n".join(f"T{i:02d}" for i in range(6)))
    c["filings_budget_sec"] = 250
    out = mod.do_work(c, args(), print, fetch=fetch_info({}), site=FakeSite([]), filings_for=filings_for, clock=lambda: next(ticks))
    text = capsys.readouterr().out
    assert len(asked) == 2 and "공시를 받지 못해 남은 4종목은 가격 조건만 봅니다 (시간 초과)" in text
    assert "T0" not in text and out["counts"]["checked"] == 6


def test_without_sec_user_agent_edgar_is_never_called(tmp_path, monkeypatch, capsys):
    class Boom:
        def __init__(self, *a, **k):
            raise AssertionError("EDGAR 를 부르면 안 된다")
    monkeypatch.setattr(mod, "Edgar", Boom)
    site = FakeSite([])
    out = mod.do_work(cfg(tmp_path), args(), print, fetch=fetch_info({}), site=site)
    assert "SEC_USER_AGENT" in capsys.readouterr().out and out["counts"]["checked"] == 3
    assert [k for _, k, _, _ in site.sent][-2:] == ["board", "lens"]


def test_sec_user_agent_is_passed_to_edgar_and_never_printed(tmp_path, monkeypatch, capsys):
    seen = {}

    class Fake:
        def __init__(self, user_agent=""):
            seen["ua"] = user_agent
            self.filings = lambda t, since: []
    monkeypatch.setattr(mod, "Edgar", Fake)
    monkeypatch.setenv("SEC_USER_AGENT", " Test Agent test@example.com ")
    mod.do_work(cfg(tmp_path), args(dry=True), print, fetch=fetch_info({}), site=FakeSite([]))
    cap = capsys.readouterr()
    assert seen["ua"] == "Test Agent test@example.com" and "test@example.com" not in cap.out + cap.err


def test_index_failure_leaves_index_empty(tmp_path):
    def fetch(t):
        if t == "SPY":
            raise ValueError("SPY 없음")
        return fetch_info({})(t)
    site = FakeSite([])
    mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch, site=site)
    assert site.docs[f"lens:{AS_OF}"]["index"] is None


def test_stale_index_leaves_index_empty(tmp_path):
    def fetch(t):
        raw = fetch_info({})(t)
        if t == "SPY":
            raw["closes"][-1][0] = "2025-01-01"
        return raw
    site = FakeSite([])
    mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch, site=site)
    assert site.docs[f"lens:{AS_OF}"]["index"] is None


# ---- 3단계: 관점 기록 덧붙이기·채점·지수, 관심 종목 기사 제목 ----

def test_history_merged_scored_and_uploaded_in_order(tmp_path):
    old = {"days": {"2025-01-02": {"value": ["AAA"], "growth": [], "event": [], "flow": []}}}
    site = FakeSite([], history=old)
    mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch_info({"AAA": {"revenueGrowth": 0.30, "earningsGrowth": 0.10}}), site=site)
    assert site.order == ["ticker"] * 3 + ["board", "lens", "lenshist", "index"]
    hist = site.extra["lenshist"]
    assert set(hist["days"]) == {"2025-01-02", AS_OF} and hist["days"][AS_OF]["growth"] == ["AAA"] and hist["days"]["2025-01-02"]["value"] == ["AAA"]
    idx = site.extra["index"]
    assert idx["t"] == "SPY" and idx["closes"] == make_raw()["closes"] and idx["closes"][-1][0] == AS_OF
    score = site.docs["board"]["lens_score"]
    assert set(score) == {"value", "growth", "event", "flow"} and set(score["growth"]) == {"1w", "1m", "3m"}
    assert score["growth"]["1w"]["n"] == 0                       # 오늘 걸린 것은 아직 며칠 뒤 종가가 없다


def test_scoring_uses_universe_closes_and_spy(tmp_path):
    # 기록의 첫 날(100거래일 전)에 AAA 가 걸렸다 → 그 뒤 5·21·63일 수익률을 SPY 와 견준다
    day0 = make_raw()["closes"][-100][0]
    site = FakeSite([], history={"days": {day0: {"value": ["AAA"], "growth": [], "event": [], "flow": []}}})
    mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch_info({}), site=site)
    v = site.docs["board"]["lens_score"]["value"]
    assert v["1w"]["n"] == 1 and v["1m"]["n"] == 1 and v["3m"]["n"] == 1


def test_history_null_is_not_a_failure(tmp_path):
    site = FakeSite([], history=None)
    out = mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch_info({}), site=site)
    assert "lenshist" in site.order and site.docs["board"]["lens_score"] is not None and out["counts"]["checked"] == 3


class NoHistory(FakeSite):
    def get_view(self, market, view):
        raise OSError("503 https://x.example/api/stock?ticker=AAA")


def test_history_read_failure_skips_scoring_and_never_overwrites(tmp_path, capsys):
    site = NoHistory([])
    mod.do_work(cfg(tmp_path), args(), print, fetch=fetch_info({}), site=site)
    cap = capsys.readouterr()
    shown = cap.out + cap.err
    assert "관점 기록을 읽지 못해 오늘 채점은 건너뜁니다" in cap.out
    assert "503" not in shown and "x.example" not in shown and "AAA" not in shown
    assert site.order == ["ticker"] * 3 + ["board", "lens"] and site.docs["board"]["lens_score"] is None


def test_stale_or_missing_spy_skips_scoring_uploads(tmp_path, capsys):
    def stale(t):
        raw = fetch_info({})(t)
        if t == "SPY":
            raw["closes"][-1][0] = "2025-01-01"
        return raw

    def dead(t):
        if t == "SPY":
            raise ValueError("SPY 없음")
        return fetch_info({})(t)
    for f in (stale, dead):
        site = FakeSite([])
        mod.do_work(cfg(tmp_path), args(), print, fetch=f, site=site)
        assert "채점은 건너뜁니다" in capsys.readouterr().out
        assert "lenshist" not in site.order and "index" not in site.order and site.docs["board"]["lens_score"] is None


def test_dry_run_reads_history_but_sends_nothing(tmp_path):
    reads = []

    class Reads(FakeSite):
        def get_view(self, market, view):
            reads.append(view)
            return super().get_view(market, view)
    site = Reads([])
    mod.do_work(cfg(tmp_path), args(dry=True), lambda m: None, fetch=fetch_info({}), site=site)
    assert reads == ["lenshist"] and site.order == []
    lines = []
    mod.do_work(cfg(tmp_path), args(dry=True), lines.append, fetch=fetch_info({}), site=NoHistory([]))   # 읽기 실패도 시험 실행은 계속
    assert "관점 기록을 읽지 못해 오늘 채점은 건너뜁니다" in lines


def fake_news(name, as_of):
    return [{"title": f"{name} jumps (ZZZ)", "source": "Wire", "date": as_of, "url": "https://example.com/a"}]


def news_cfg(tmp_path):
    c = cfg(tmp_path)
    c["news_enabled"] = True
    return c


def test_news_only_for_watch_tickers_and_counted(tmp_path):
    asked = []

    def news(name, as_of):
        asked.append(name)
        return fake_news(name, as_of) if name.startswith("ZZZ") else []
    site = FakeSite(["ZZZ", "AAA"])
    out = mod.do_work(news_cfg(tmp_path), args(), lambda m: None, fetch=fetch_ok, site=site, news=news)
    assert sorted(asked) == ["AAA Corp", "ZZZ Corp"]
    assert site.docs["ticker:ZZZ"]["news"][0]["url"].startswith("https://") and site.docs["ticker:AAA"]["news"] == []
    assert site.docs["ticker:BBB"]["news"] == []
    assert out["counts"]["news"] == 2 and "관심 종목 기사 제목 2종목" in out["lines"]
    assert "기사" not in mod.build_summary(out["counts"], 3)


def test_news_disabled_asks_nothing(tmp_path):
    def boom(name, as_of):
        raise AssertionError("끄면 받지 않는다")
    site = FakeSite(["ZZZ"])
    out = mod.do_work(cfg(tmp_path), args(), lambda m: None, fetch=fetch_ok, site=site, news=boom)
    assert out["counts"]["news"] == 0 and site.docs["ticker:ZZZ"]["news"] == [] and not any("기사" in l for l in out["lines"])


def test_news_failures_are_counted_and_stop_after_five_straight(tmp_path, capsys):
    asked = []

    def news(name, as_of):
        asked.append(name)
        if len(asked) == 1:
            return []
        raise RuntimeError(f"403 {name}")
    watch = [f"W{i:02d}" for i in range(12)]
    out = mod.do_work(news_cfg(tmp_path), args(), print, fetch=fetch_ok, site=FakeSite(watch), news=news)
    cap = capsys.readouterr()
    shown = cap.out + cap.err
    assert len(asked) == 6 and out["counts"]["news"] == 1          # 성공 1번 뒤 연달아 5번 실패
    assert shown.count("기사 제목을 받지 못해") == 1
    assert "403" not in shown and "W0" not in shown and "Corp" not in shown


def test_news_some_failures_are_summarised(tmp_path, capsys):
    def news(name, as_of):
        if name.startswith("W01"):
            raise RuntimeError("x")
        return []
    out = mod.do_work(news_cfg(tmp_path), args(), print, fetch=fetch_ok, site=FakeSite(["W00", "W01", "W02"]), news=news)
    assert "기사 제목을 받지 못해 건너뛴 종목 1건" in capsys.readouterr().out and out["counts"]["news"] == 2


def test_news_never_leaks_names_or_titles(tmp_path, capsys):
    def noisy(name, as_of):
        print("제목", name)
        print(name, file=sys.stderr)
        warnings.warn(name)
        return fake_news(name, as_of)
    site = FakeSite(["ZZZ"])
    out = mod.do_work(news_cfg(tmp_path), args(), print, fetch=fetch_ok, site=site, news=noisy)
    cap = capsys.readouterr()
    shown = cap.out + cap.err + " ".join(out["lines"]) + " ".join(v[1] for v in out["tasks"].values())
    for bad in ("AAA", "BBB", "CCC", "ZZZ", "Corp", "jumps"):
        assert bad not in shown
    assert "jumps" in site.docs["ticker:ZZZ"]["news"][0]["title"]       # 자료는 사이트 저장 공간에만 간다


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
    s.ingest("us", "lens", {"b": 2}, date="2026-10-02")
    assert calls[0] == ("GET", "https://x.example/api/stock", {"market": "us", "view": "watch"}, None)
    assert calls[1] == ("POST", "https://x.example/api/stock/ingest", {"market": "us", "kind": "ticker", "doc": {"a": 1}, "ticker": "ORCL"}, {"X-Live-Token": "tok"})
    assert calls[2][2] == {"market": "us", "kind": "lens", "doc": {"b": 2}, "date": "2026-10-02"}
    assert analyst_publish.Site("https://x.example", http=Http())._headers() == {}


class Resp:
    def __init__(self, status):
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class ScriptedHttp:
    """post 를 부를 때마다 steps 의 다음 값(상태 코드, 또는 던질 예외)으로 답한다."""
    def __init__(self, *steps):
        self.steps, self.posts = list(steps), 0

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts += 1
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return Resp(step)


def make_site(*steps):
    waits = []
    return analyst_publish.Site("https://x.example", http=ScriptedHttp(*steps), sleep=waits.append), waits


def test_ingest_retries_once_after_network_error_or_5xx():
    for first in (OSError("끊김"), 503):
        site, waits = make_site(first, 200)
        site.ingest("us", "board", {})
        assert site.http.posts == 2 and waits == [2]


def test_ingest_gives_up_after_one_retry():
    site, waits = make_site(503, 502)
    with pytest.raises(RuntimeError):
        site.ingest("us", "board", {})
    assert site.http.posts == 2 and waits == [2]
    site, _ = make_site(OSError("끊김"), OSError("끊김"))
    with pytest.raises(OSError):
        site.ingest("us", "board", {})


def test_ingest_does_not_retry_client_errors():
    site, waits = make_site(400, 200)
    with pytest.raises(RuntimeError):
        site.ingest("us", "board", {})
    assert site.http.posts == 1 and waits == []
