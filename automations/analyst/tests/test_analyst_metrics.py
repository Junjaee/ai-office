"""analyst_metrics — 원자료에서 종목 기록 만들기(순수 계산)."""
import math

import analyst_metrics as m


def make_raw(**over):
    closes = [[f"2025-{1 + i // 22:02d}-{1 + i % 22:02d}", 100.0 + i * 0.2] for i in range(250)]
    closes[100][1] = closes[99][1] * 1.10          # +10% 큰 변동일
    closes[-1][1] = 150.0; closes[-2][1] = 148.0
    raw = {"t": "TEST", "name": "Test Corp", "exchange": "NMS", "sector": "Technology",
           "closes": closes, "volumes": [1000] * 245 + [3000] * 5,
           "ath": 200.0, "ath_date": "2024-01-02",
           "info": {"forwardPE": 12.5, "trailingPE": 20.0, "priceToBook": 6.0, "marketCap": 4e11,
                    "revenueGrowth": 0.296, "earningsGrowth": 0.545, "operatingMargins": 0.356,
                    "ebitda": 30e9, "totalDebt": 169e9, "totalCash": 37e9, "freeCashflow": -45e9,
                    "operatingCashflow": 46e9, "totalRevenue": 71e9, "targetMeanPrice": 238.0,
                    "targetLowPrice": 110.0, "targetHighPrice": 400.0, "numberOfAnalystOpinions": 41},
           "next_earn": "2026-12-11",
           "annual": [{"fy": 2025, "rev": 57e9, "ni": 12e9, "capex": 21e9, "fcf": -0.4e9}]}
    raw.update(over)
    return raw


def test_build_record_prices_and_ratios():
    r = m.build_record(make_raw())
    assert r["t"] == "TEST" and r["as_of"] == r["chart"][-1][0]
    assert r["price"] == 150.0
    assert round(r["chg_pct"], 2) == round((150 / 148 - 1) * 100, 2)
    assert r["hi52"] == max(c for _, c in make_raw()["closes"])
    assert r["ath_pct"] == -25.0 and r["ath"] == 200.0
    assert r["rev_g"] == 29.6 and r["eps_g"] == 54.5 and round(r["opm"], 1) == 35.6   # % 단위
    assert r["net_debt_ebitda"] == round((169e9 - 37e9) / 30e9, 2)
    assert r["tgt"] == {"mean": 238.0, "lo": 110.0, "hi": 400.0, "n": 41}
    assert len(r["spark"]) == m.SPARK_POINTS and r["spark"][-1] == 150.0
    assert len(r["chart"]) == m.CHART_POINTS and r["chart"][-1][1] == 150.0
    assert r["dv_ratio"] > 1.5                      # 마지막 5일 거래량이 3배
    assert r["financial"] is False


def test_missing_values_become_none_not_zero():
    raw = make_raw(info={"forwardPE": float("nan"), "ebitda": 0}, next_earn=None, annual=[])
    r = m.build_record(raw)
    assert r["fpe"] is None and r["rev_g"] is None and r["net_debt_ebitda"] is None and r["tgt"] is None
    assert r["next_earn"] is None and r["annual"] == []


def test_big_moves_picks_largest_days_in_date_order():
    moves = m.big_moves(make_raw()["closes"])
    assert moves and moves[0]["pct"] >= 7.0
    assert [x["date"] for x in moves] == sorted(x["date"] for x in moves)
    assert len(m.big_moves(make_raw()["closes"], limit=1)) == 1


def test_thin_keeps_first_and_last():
    assert m.thin(list(range(10)), 4) == [0, 3, 6, 9]
    assert m.thin([1, 2], 5) == [1, 2]
    assert m.num("x") is None and m.num(None) is None and m.num(float("inf")) is None and m.num("3.5") == 3.5
    assert not math.isnan(m.num(1))


def test_financial_sector_flag():
    assert m.build_record(make_raw(sector="Financial Services"))["financial"] is True


def test_missing_cash_requires_none_for_net_debt():
    # When totalCash is missing but totalDebt and ebitda are present,
    # net_debt_ebitda must be None (not a calculation using 0 for cash)
    info_no_cash = {"forwardPE": 12.5, "trailingPE": 20.0, "priceToBook": 6.0,
                    "ebitda": 30e9, "totalDebt": 169e9}  # No totalCash
    raw = make_raw(info=info_no_cash)
    r = m.build_record(raw)
    assert r["net_debt_ebitda"] is None
    assert r["cash"] is None
    # Verify that with all three present, calculation works
    r_full = m.build_record(make_raw())
    assert r_full["net_debt_ebitda"] == round((169e9 - 37e9) / 30e9, 2)
    assert r_full["cash"] == 37e9


def _raw70(last_close=110.0, last_vol=1000.0):
    closes = [[f"2026-07-{i + 1:02d}" if i < 31 else f"2026-08-{i - 30:02d}" if i < 62 else f"2026-09-{i - 61:02d}", 100.0] for i in range(70)]
    closes[-1][1] = last_close
    vols = [1000.0] * 70
    vols[-1] = last_vol
    return {"t": "AAA", "closes": closes, "volumes": vols, "info": {}}


def test_dv1_ratio_is_last_day_over_60day_average():
    rec = m.build_record(_raw70(last_close=100.0, last_vol=4000.0))
    assert rec["dv1_ratio"] == round(4000 * 100 / ((59 * 1000 * 100 + 4000 * 100) / 60), 2)


def test_dv1_ratio_is_none_when_last_day_has_no_volume():
    assert m.build_record(_raw70(last_vol=0))["dv1_ratio"] is None


def test_above_ma20_true_when_last_close_over_20day_mean():
    assert m.build_record(_raw70(last_close=110.0))["above_ma20"] is True
    assert m.build_record(_raw70(last_close=90.0))["above_ma20"] is False


def test_short_history_gives_none_not_zero():
    raw = _raw70()
    raw["closes"], raw["volumes"] = raw["closes"][-10:], raw["volumes"][-10:]
    rec = m.build_record(raw)
    assert rec["dv1_ratio"] is None and rec["above_ma20"] is None


def test_build_record_currency_and_local_name_defaults_and_kr():
    r = m.build_record(make_raw())
    assert r["currency"] == "USD" and r["name_local"] is None
    r = m.build_record(make_raw(currency="KRW", name_local="삼성전자"))
    assert r["currency"] == "KRW" and r["name_local"] == "삼성전자"
