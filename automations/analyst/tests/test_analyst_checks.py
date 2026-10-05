"""analyst_checks — 중앙값, 점검표 7가지, 점검 요약, 판 한 줄."""
import analyst_checks as c

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
    assert set(row) == {"t", "name", "price", "chg_pct", "spark", "ath_pct", "off_hi_pct", "fpe", "n_pass", "n_care", "n_warn", "diag", "next_earn", "warn_keys"}


def test_peers_same_sector_nearest_size():
    recs = [rec(t="A", mcap=100), rec(t="B", mcap=90), rec(t="C", mcap=500), rec(t="D", mcap=110), rec(t="E", sector="Energy", mcap=100), rec(t="N", mcap=105, fpe=None)]
    out = c.peers(rec(t="A", mcap=100), recs, n=2)
    assert [p["t"] for p in out] == ["B", "D"]
