"""analyst_checks — 중앙값, 점검표 7가지, 점검 요약, 판 한 줄."""
import analyst_checks as c
from analyst_checks import LENS_ORDER, lens_info, lenses, load_rules

RULES = c.load_rules()


def rec(**over):
    r = {"t": "AAA", "name": "A", "sector": "Technology", "financial": False, "price": 100.0, "chg_pct": 1.0,
         "spark": [1, 2], "ath_pct": -5.0, "off_hi_pct": -5.0, "fpe": 12.0, "rev_g": 29.6, "eps_g": 54.5, "opm": 35.6,
         "net_debt_ebitda": 1.0, "fcf": 5e9, "ocf": 9e9, "next_earn": "2026-10-22", "mcap": 1e11}
    r.update(over)
    return r


MED = {"all": {"fpe": 24.0, "opm": 20.0}, "sector": {"Technology": {"fpe": 24.0, "opm": 30.0, "n": 8}}}


def states(r):
    return {x["key"]: x["state"] for x in c.run_checks(r, MED, RULES)}


def test_all_pass_and_text_carries_numbers():
    out = c.run_checks(rec(), MED, RULES)
    assert [x["key"] for x in out] == ["가치", "매출 성장", "이익 방향", "수익성", "빚", "현금흐름", "추세"]
    assert all(x["state"] == "pass" for x in out)
    assert "12.0배" in out[0]["text"] and "24.0배" in out[0]["text"] and "업종" in out[0]["text"]


def test_warnings():
    s = states(rec(fpe=40.0, rev_g=-3.0, eps_g=-30.0, opm=-2.0, net_debt_ebitda=4.4, fcf=-45e9, ocf=-1e9, off_hi_pct=-57.0))
    assert set(s.values()) == {"warn"}


def test_care_band():
    s = states(rec(fpe=30.0, rev_g=4.0, eps_g=-10.0, opm=12.0, net_debt_ebitda=3.0, fcf=-1e9, ocf=5e9, off_hi_pct=-20.0))
    assert set(s.values()) == {"care"}


def test_missing_is_na_and_financials_skip_debt_and_cash():
    s = states(rec(fpe=None, rev_g=None, eps_g=None, opm=None, net_debt_ebitda=None, fcf=None, ocf=None))
    assert s["가치"] == "na" and s["매출 성장"] == "na" and s["빚"] == "na" and s["현금흐름"] == "na"
    f = c.run_checks(rec(financial=True, net_debt_ebitda=9.0, fcf=-1e9), MED, RULES)
    by = {x["key"]: x for x in f}
    assert by["빚"]["state"] == "na" and by["현금흐름"]["state"] == "na" and "해당 없음" in by["빚"]["text"]


def test_negative_forward_pe_is_warn_loss():
    by = {x["key"]: x for x in c.run_checks(rec(fpe=-8.0), MED, RULES)}
    assert by["가치"]["state"] == "warn" and "적자" in by["가치"]["text"]


def test_small_sector_falls_back_to_market_median():
    med = {"all": {"fpe": 20.0, "opm": 15.0}, "sector": {"Technology": {"fpe": 99.0, "opm": 99.0, "n": 2}}}
    ref = c.ref_for(rec(), med, RULES["sector_min"])
    assert ref == {"fpe": 20.0, "opm": 15.0, "label": "시장"}


def test_medians_and_diag_and_row():
    recs = [rec(t=f"T{i}", fpe=10.0 + i, opm=20.0 + i) for i in range(6)] + [rec(t="F", sector="Energy", fpe=5.0, opm=5.0)]
    med = c.medians(recs, 5)
    assert med["sector"]["Technology"]["n"] == 6 and med["sector"]["Technology"]["fpe"] == 12.5
    assert med["sector"]["Energy"]["n"] == 1 and med["all"]["fpe"] == 12.0
    checks = c.run_checks(rec(net_debt_ebitda=4.4, fcf=-1e9, ocf=-1e9), MED, RULES)
    assert c.diag(checks) == "좋음: 가치·매출 성장·이익 방향·수익성·추세 / 경고: 빚·현금흐름"
    row = c.board_row(rec(net_debt_ebitda=4.4, fcf=-1e9, ocf=-1e9), checks)
    assert row["n_pass"] == 5 and row["n_care"] == 0 and row["n_warn"] == 2 and row["warn_keys"] == ["빚", "현금흐름"]
    assert set(row) == {"t", "name", "price", "chg_pct", "spark", "ath_pct", "off_hi_pct", "fpe", "n_pass", "n_care", "n_warn", "diag", "next_earn", "warn_keys",
                       "sector", "rev_g", "nde", "dv_ratio", "lenses"}


def test_peers_same_sector_nearest_size():
    recs = [rec(t="A", mcap=100), rec(t="B", mcap=90), rec(t="C", mcap=500), rec(t="D", mcap=110), rec(t="E", sector="Energy", mcap=100), rec(t="N", mcap=105, fpe=None)]
    out = c.peers(rec(t="A", mcap=100), recs, n=2)
    assert [p["t"] for p in out] == ["B", "D"]


def _ck(**states):
    base = {k: "care" for k in ["가치", "매출 성장", "이익 방향", "수익성", "빚", "현금흐름", "추세"]}
    base.update(states)
    return [{"key": k, "state": s, "text": f"{k} 문장"} for k, s in base.items()]


RULES = load_rules()


def test_value_lens_needs_value_debt_cashflow_all_pass():
    rec = {"t": "A"}
    assert [x["id"] for x in lenses(rec, _ck(가치="pass", 빚="pass", 현금흐름="pass"), [], RULES)] == ["value"]
    assert lenses(rec, _ck(가치="pass", 빚="pass", 현금흐름="care"), [], RULES) == []
    assert lenses(rec, _ck(가치="pass", 빚="na", 현금흐름="na"), [], RULES) == []     # 금융업은 걸리지 않는다


def test_growth_lens_needs_revenue_15_and_rising_profit():
    hit = lenses({"rev_g": 15.0, "eps_g": 0.1}, _ck(), [], RULES)
    assert hit == [{"id": "growth", "why": "매출 +15.0% · 이익 +0.1% (전년 대비)"}]
    assert lenses({"rev_g": 14.9, "eps_g": 50.0}, _ck(), [], RULES) == []
    assert lenses({"rev_g": 30.0, "eps_g": 0.0}, _ck(), [], RULES) == []
    assert lenses({"rev_g": 30.0, "eps_g": None}, _ck(), [], RULES) == []


def test_event_lens_by_major_filing_or_big_move_with_volume():
    ev = [{"date": "2026-09-30", "kind": "실적 발표"}, {"date": "2026-09-28", "kind": "인수·매각 완료"}, {"date": "2026-09-27", "kind": "임원 교체"}]
    assert lenses({}, _ck(), ev, RULES) == [{"id": "event", "why": "9월 30일 실적 발표 공시 외 1건"}]
    assert lenses({}, _ck(), [{"date": "2026-09-27", "kind": "임원 교체"}], RULES) == []          # 주요 공시가 아님
    assert lenses({"chg_pct": -7.0, "dv1_ratio": 3.0}, _ck(), [], RULES) == [{"id": "event", "why": "하루 -7.0% · 거래대금 평소의 3.0배"}]
    assert lenses({"chg_pct": 9.0, "dv1_ratio": 2.9}, _ck(), [], RULES) == []
    assert lenses({"chg_pct": 9.0, "dv1_ratio": None}, _ck(), [], RULES) == []


def test_flow_lens_needs_volume_and_price_above_20day_mean():
    assert lenses({"dv_ratio": 1.5, "above_ma20": True}, _ck(), [], RULES) == [{"id": "flow", "why": "최근 5일 거래대금 평소의 1.5배 · 20일 평균 위"}]
    assert lenses({"dv_ratio": 2.0, "above_ma20": False}, _ck(), [], RULES) == []
    assert lenses({"dv_ratio": None, "above_ma20": True}, _ck(), [], RULES) == []


def test_lenses_come_in_fixed_order_and_info_covers_all():
    rec = {"rev_g": 20.0, "eps_g": 5.0, "dv_ratio": 2.0, "above_ma20": True}
    assert [x["id"] for x in lenses(rec, _ck(가치="pass", 빚="pass", 현금흐름="pass"), [], RULES)] == ["value", "growth", "flow"]
    info = lens_info(RULES)
    assert list(info) == LENS_ORDER and all(info[k]["label"] and info[k]["rule"] for k in LENS_ORDER)
    assert "15" in info["growth"]["rule"] and "1.5" in info["flow"]["rule"]


def test_board_row_carries_lens_fields():
    rec = {"t": "A", "name": "A Inc", "price": 1.0, "sector": "Technology", "rev_g": 12.0, "net_debt_ebitda": 0.5, "dv_ratio": 1.2}
    row = c.board_row(rec, _ck(), [{"id": "flow", "why": "x"}])
    assert (row["sector"], row["rev_g"], row["nde"], row["dv_ratio"], row["lenses"]) == ("Technology", 12.0, 0.5, 1.2, [{"id": "flow", "why": "x"}])
    assert c.board_row(rec, _ck())["lenses"] == []
