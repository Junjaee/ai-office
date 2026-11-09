"""SEC XBRL(companyfacts) 재무값 읽기 — 시점을 지킨다.

원칙: 모든 값에 처음 공시된 날(filed)을 붙이고, 기준일까지 공시된 것만 쓴다.
매출·이익·현금흐름·배당·자사주는 분기 값으로 쪼갠 뒤 최근 4분기 합(TTM)을 만든다.
검증 근거: docs/stock/12-재무제표-팩터-검증.md (해석기 docs/stock/scripts/fparse.py 와 같은 논리).
"""
from __future__ import annotations

import json
import zipfile
from datetime import date

import numpy as np
import pandas as pd

# 흐름 항목(기간이 있는 값). 회계기준 변경으로 태그가 바뀌는 회사가 많아 후보를 전부 합친다
FLOW = {
    "rev": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"],
    "ni": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "div": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    "buyback": ["PaymentsForRepurchaseOfCommonStock"],
}
# 시점 항목(잔액)
INSTANT = {
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
}
SHARES_DIL = ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"]
SHARES_DEI = ["EntityCommonStockSharesOutstanding"]
KEYS = list(FLOW) + list(INSTANT) + ["shares"]


def _facts(cf: dict, ns: str, tags: list[str], units: list[str]) -> list[dict]:
    out: list[dict] = []
    for tag in tags:
        node = cf.get("facts", {}).get(ns, {}).get(tag)
        if not node:
            continue
        for u in units:
            arr = node.get("units", {}).get(u)
            if arr:
                out.extend(arr)
                break
    return out


def _dedupe_earliest(rows: list[dict], key) -> list[dict]:
    """같은 기간 값이 여러 공시에 반복되면 가장 먼저 공시된 것만(그때 알 수 있던 값)."""
    kept: dict = {}
    for r in rows:
        k = key(r)
        if k not in kept or r["filed"] < kept[k]["filed"]:
            kept[k] = r
    return list(kept.values())


def flow_ttm(arr: list[dict]) -> list[tuple]:
    """기간 값 목록 → [(기간 끝, 공시일, 최근 12개월 합)] 정렬."""
    rows = []
    for r in arr:
        if "start" not in r or r.get("val") is None:
            continue
        s, e = pd.Timestamp(r["start"]), pd.Timestamp(r["end"])
        rows.append(dict(start=s, end=e, days=(e - s).days, val=float(r["val"]), filed=pd.Timestamp(r["filed"])))
    rows = _dedupe_earliest(rows, lambda r: (r["start"], r["end"]))
    if not rows:
        return []
    by_end: dict = {}
    for r in rows:
        by_end.setdefault(r["end"], []).append(r)
    ends = sorted(by_end)
    q: dict = {}  # 분기 값: 끝 → (값, 공시일)
    for e in ends:
        direct = [r for r in by_end[e] if 75 <= r["days"] <= 105]
        if direct:
            r = min(direct, key=lambda r: r["filed"])
            q[e] = (r["val"], r["filed"])
            continue
        done = False
        for r in sorted(by_end[e], key=lambda r: r["days"]):   # 누적값 − 같은 회계연도의 이전 누적값
            if r["days"] < 160 or done:
                continue
            for e2 in ends:
                if e2 >= e:
                    break
                for r2 in by_end[e2]:
                    if r2["start"] == r["start"] and 75 <= (r["days"] - r2["days"]) <= 105:
                        q[e] = (r["val"] - r2["val"], max(r["filed"], r2["filed"]))
                        done = True
    out: set = set()
    qe = sorted(q)
    for i, e in enumerate(qe):
        win = [x for x in qe[:i + 1] if (e - x).days <= 300]
        if len(win) >= 4:
            w = win[-4:]
            out.add((e, max(q[x][1] for x in w), sum(q[x][0] for x in w)))
    for e in ends:   # 연간 값이 직접 있으면 그것도(분기 합이 없을 때 대비)
        ann = [r for r in by_end[e] if 350 <= r["days"] <= 380]
        if ann and not any(o[0] == e for o in out):
            r = min(ann, key=lambda r: r["filed"])
            out.add((e, r["filed"], r["val"]))
    return sorted(out)


def instant(arr: list[dict]) -> list[tuple]:
    rows = [dict(end=pd.Timestamp(r["end"]), val=float(r["val"]), filed=pd.Timestamp(r["filed"]))
            for r in arr if r.get("val") is not None and "start" not in r]
    rows = _dedupe_earliest(rows, lambda r: r["end"])
    return sorted((r["end"], r["filed"], r["val"]) for r in rows)


def shares_series(cf: dict) -> list[tuple]:
    """주식수 [(기간 끝, 공시일, 값)].

    표지의 주식수(dei)는 자리표시값(1,000)·보고 중단·주식 종류별 따로 표기 같은 문제가 많아,
    손익계산서의 희석 가중평균 주식수(모든 종류 합)를 먼저 쓴다. 같은 기간 끝에 분기·누적이 같이 있으면
    짧은 기간(최근 평균)을 고른다. 없을 때만 표지 값을 쓰되 같은 공시의 종류별 값은 합친다.
    """
    rows = []
    for r in _facts(cf, "us-gaap", SHARES_DIL, ["shares"]):
        if "start" in r and r.get("val"):
            s, e = pd.Timestamp(r["start"]), pd.Timestamp(r["end"])
            if 60 <= (e - s).days <= 380 and float(r["val"]) > 1000:
                rows.append(dict(end=e, days=(e - s).days, val=float(r["val"]), filed=pd.Timestamp(r["filed"])))
    best: dict = {}
    for r in rows:
        k = r["end"]
        if k not in best or (r["days"], r["filed"]) < (best[k]["days"], best[k]["filed"]):
            best[k] = r
    out = sorted((r["end"], r["filed"], r["val"]) for r in best.values())
    if len(out) >= 4:
        return out
    agg: dict = {}   # 같은 공시(끝·공시일)의 서로 다른 값 = 주식 종류별 → 합친다. 똑같은 중복은 한 번만
    for r in _facts(cf, "dei", SHARES_DEI, ["shares"]):
        if r.get("val") and "start" not in r:
            agg.setdefault((pd.Timestamp(r["end"]), pd.Timestamp(r["filed"])), set()).add(float(r["val"]))
    rows = [dict(end=e, filed=f, val=sum(vs)) for (e, f), vs in agg.items() if sum(vs) > 1000]
    rows = _dedupe_earliest(rows, lambda r: r["end"])
    return sorted((r["end"], r["filed"], r["val"]) for r in rows)


def parse(cf: dict) -> dict[str, list[tuple]]:
    """회사 하나의 companyfacts → 항목별 [(기간 끝, 공시일, 값)]."""
    out: dict = {k: flow_ttm(_facts(cf, "us-gaap", tags, ["USD"])) for k, tags in FLOW.items()}
    for k, tags in INSTANT.items():
        out[k] = instant(_facts(cf, "us-gaap", tags, ["USD"]))
    out["shares"] = shares_series(cf)
    return out


def as_of(series: list[tuple], day: date) -> tuple[float, date | None]:
    """기준일까지 공시된 것 중 가장 최근 기간의 값과 그 기간 끝. 없으면 (nan, None)."""
    best_end, best_val = None, float("nan")
    for end, filed, val in sorted(series, key=lambda x: x[1]):
        if filed.date() > day:
            break
        if best_end is None or end >= best_end:
            best_end, best_val = end, val
    return best_val, (best_end.date() if best_end is not None else None)


def values_as_of(parsed: dict, day: date) -> dict:
    """항목별 값 + 가장 오래된 기간 끝(자료가 얼마나 묵었는지 보려고)."""
    out: dict = {}
    oldest = None
    for k in KEYS:
        v, e = as_of(parsed.get(k, []), day)
        out[k] = v
        if k in ("rev", "ni", "ocf", "shares") and e is not None and (oldest is None or e < oldest):
            oldest = e
        if k == "shares":
            out["shares_end"] = e
    out["period_end"] = oldest
    return out


def read_zip(zip_path: str, cik_by_ticker: dict[str, int], day: date, progress=None) -> dict[str, dict]:
    """companyfacts.zip 에서 필요한 회사만 읽어 기준일 시점 값을 만든다. {티커: 값들}."""
    out: dict = {}
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        for i, (t, cik) in enumerate(cik_by_ticker.items()):
            fn = f"CIK{int(cik):010d}.json"
            if fn not in names:
                continue
            try:
                cf = json.loads(z.read(fn))
                out[t] = values_as_of(parse(cf), day)
            except (ValueError, KeyError, zipfile.BadZipFile):
                continue
            if progress and (i + 1) % 100 == 0:
                progress(f"재무제표 해석 {i + 1}/{len(cik_by_ticker)}")
    return out


def coverage(values: dict[str, dict]) -> int:
    """핵심 값(순이익·매출·현금흐름·자본·주식수)이 다 있는 회사 수."""
    need = ("ni", "rev", "ocf", "equity", "shares")
    return sum(1 for v in values.values() if all(np.isfinite(v.get(k, float("nan"))) for k in need))
