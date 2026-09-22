"""SEC XBRL companyfacts → 시점별 재무 수치.

원칙: 모든 값에 처음 공시된 날(filed)을 붙인다. 백테스트에서는 filed <= 재조정일 인 값만 쓴다.
흐름 항목(매출·이익·현금흐름)은 분기 값으로 쪼갠 뒤 최근 4분기 합(TTM)을 만든다.
"""
import json

import numpy as np
import pandas as pd

FLOW = {
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"],
    "ni": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "oi": ["OperatingIncomeLoss"],
    "gp": ["GrossProfit"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "div": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "buyback": ["PaymentsForRepurchaseOfCommonStock"],
    "rnd": ["ResearchAndDevelopmentExpense"],
    "intexp": ["InterestExpense"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet"],
    "tax": ["IncomeTaxExpenseBenefit"],
}
INSTANT = {
    "assets": ["Assets"],
    "liab": ["Liabilities"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "curassets": ["AssetsCurrent"],
    "curliab": ["LiabilitiesCurrent"],
    "ltdebt": ["LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "ppe": ["PropertyPlantAndEquipmentNet"],
}
SHARES = ["EntityCommonStockSharesOutstanding"]  # dei
SHARES_GAAP = ["CommonStockSharesOutstanding", "WeightedAverageNumberOfDilutedSharesOutstanding"]


def _facts(cf, ns, tags, unit_pref):
    """후보 태그를 전부 합친다(회계기준 변경으로 태그가 바뀌는 회사가 많다). 겹치는 기간은 뒤에서 걸러진다."""
    out = []
    for tag in tags:
        node = cf.get("facts", {}).get(ns, {}).get(tag)
        if not node:
            continue
        for u in unit_pref:
            arr = node.get("units", {}).get(u)
            if arr:
                out.extend(arr)
                break
    return out


def _dedupe_earliest(rows, key):
    """같은 기간의 값이 여러 공시에 반복되면 가장 먼저 공시된 것을 남긴다(그때 알 수 있었던 값)."""
    out = {}
    for r in rows:
        k = key(r)
        if k not in out or r["filed"] < out[k]["filed"]:
            out[k] = r
    return list(out.values())


def flow_ttm(arr):
    """duration 항목 → [(end, filed, ttm)] 정렬."""
    rows = []
    for r in arr:
        if "start" not in r or r.get("val") is None:
            continue
        s, e = pd.Timestamp(r["start"]), pd.Timestamp(r["end"])
        rows.append(dict(start=s, end=e, days=(e - s).days, val=float(r["val"]),
                         filed=pd.Timestamp(r["filed"])))
    rows = _dedupe_earliest(rows, lambda r: (r["start"], r["end"]))
    if not rows:
        return []
    by_end = {}
    for r in rows:
        by_end.setdefault(r["end"], []).append(r)
    q = {}  # 분기 값: end -> (val, filed)
    ends = sorted(by_end)
    for e in ends:
        cands = by_end[e]
        direct = [r for r in cands if 75 <= r["days"] <= 105]
        if direct:
            r = min(direct, key=lambda r: r["filed"])
            q[e] = (r["val"], r["filed"])
            continue
        # 누적값 - 같은 회계연도의 이전 누적값
        done = False
        for r in sorted(cands, key=lambda r: r["days"]):
            if r["days"] < 160 or done:
                continue
            for e2 in ends:
                if e2 >= e:
                    break
                for r2 in by_end[e2]:
                    if r2["start"] == r["start"] and 75 <= (r["days"] - r2["days"]) <= 105:
                        q[e] = (r["val"] - r2["val"], max(r["filed"], r2["filed"]))
                        done = True
    out = set()
    qe = sorted(q)
    for i, e in enumerate(qe):
        win = [x for x in qe[:i + 1] if (e - x).days <= 300]
        if len(win) >= 4:
            w = win[-4:]
            out.add((e, max(q[x][1] for x in w), sum(q[x][0] for x in w)))
    for e in ends:  # 연간 값이 직접 있으면 그것도 쓴다(분기 합이 없을 때 대비)
        ann = [r for r in by_end[e] if 350 <= r["days"] <= 380]
        if ann and not any(o[0] == e for o in out):
            r = min(ann, key=lambda r: r["filed"])
            out.add((e, r["filed"], r["val"]))
    return sorted(out)


def instant(arr):
    rows = [dict(end=pd.Timestamp(r["end"]), val=float(r["val"]), filed=pd.Timestamp(r["filed"]))
            for r in arr if r.get("val") is not None and "start" not in r]
    rows = _dedupe_earliest(rows, lambda r: r["end"])
    return sorted((r["end"], r["filed"], r["val"]) for r in rows)


def parse(cf):
    out = {}
    for k, tags in FLOW.items():
        out[k] = flow_ttm(_facts(cf, "us-gaap", tags, ["USD"]))
    for k, tags in INSTANT.items():
        out[k] = instant(_facts(cf, "us-gaap", tags, ["USD"]))
    sh = _facts(cf, "dei", SHARES, ["shares"])
    if len(sh) < 8:
        sh = _facts(cf, "us-gaap", SHARES_GAAP, ["shares"]) or sh
    out["shares"] = instant(sh)
    return out


def pit(series, dates):
    """series: [(end, filed, val)] → 각 날짜에 그날까지 공시된 것 중 가장 최근 기간의 값과 그 기간 끝."""
    n = len(dates)
    if not series:
        return np.full(n, np.nan), np.full(n, np.datetime64("NaT"), dtype="datetime64[ns]")
    df = pd.DataFrame(series, columns=["end", "filed", "val"]).sort_values(["filed", "end"])
    filed = df["filed"].values.astype("datetime64[ns]")
    ends = df["end"].values.astype("datetime64[ns]")
    vals = df["val"].values
    best_end = np.maximum.accumulate(ends)
    best_val = np.empty(len(df))
    cur_e = ends[0]
    cur_v = vals[0]
    for i in range(len(df)):
        if ends[i] >= cur_e:
            cur_e, cur_v = ends[i], vals[i]
        best_val[i] = cur_v
    idx = np.searchsorted(filed, np.asarray(dates, dtype="datetime64[ns]"), side="right") - 1
    ok = idx >= 0
    j = np.clip(idx, 0, None)
    v = np.where(ok, best_val[j], np.nan)
    e = np.where(ok, best_end[j], np.datetime64("NaT"))
    return v, e


def value_at_end(series, end_dates, filed_before, tol=45):
    """end ≈ end_dates[i] (±tol일), filed <= filed_before[i] 인 값. 1년 전 값 찾기용."""
    n = len(end_dates)
    out = np.full(n, np.nan)
    if not series:
        return out
    df = pd.DataFrame(series, columns=["end", "filed", "val"])
    ends = df["end"].values.astype("datetime64[ns]")
    filed = df["filed"].values.astype("datetime64[ns]")
    vals = df["val"].values
    for i in range(n):
        e = end_dates[i]
        if pd.isna(e):
            continue
        d = np.abs((ends - np.datetime64(e)) / np.timedelta64(1, "D"))
        m = (d <= tol) & (filed <= np.datetime64(filed_before[i]))
        if m.any():
            out[i] = vals[np.argmin(np.where(m, d, 1e9))]
    return out


if __name__ == "__main__":
    cf = json.load(open("cf_test.json"))
    p = parse(cf)
    print("애플 (CIK 320193)")
    for k in ["rev", "ni", "ocf", "assets", "equity", "shares"]:
        s = p[k]
        print(f"  {k:8s} {len(s):3d}개  첫 {s[0][0].date()}(공시 {s[0][1].date()})  "
              f"마지막 {s[-1][0].date()}(공시 {s[-1][1].date()}) 값 {s[-1][2]:,.0f}")
    dates = pd.DatetimeIndex(["2015-06-30", "2020-06-30", "2025-06-30"])
    v, e = pit(p["rev"], dates)
    for d, vv, ee in zip(dates, v, e):
        print(f"  {d.date()} 시점에 알 수 있던 최근 12개월 매출: {vv/1e9:,.1f}십억달러 (기간 끝 {pd.Timestamp(ee).date()})")
    v, e = pit(p["ni"], dates)
    print("  같은 시점 순이익(십억달러):", [f"{x/1e9:.1f}" for x in v])
    v, e = pit(p["shares"], dates)
    print("  같은 시점 주식수(억주):", [f"{x/1e8:.1f}" for x in v])
