"""SEC 묶음(companyfacts.zip)에서 659개 회사를 해석해 재조정일 × 종목 표를 만든다.

표의 각 칸 = 그 재조정일까지 공시된 것 중 가장 최근 기간의 값 (미래 정보 없음).
"""
import json
import time
import zipfile

import numpy as np
import pandas as pd

import fparse as F
import qengine as Q

cik = json.load(open("cik_map.json"))
z = zipfile.ZipFile("companyfacts.zip")
names = set(z.namelist())
REBAL = Q.REBAL
TICK = Q.TICK
TI = Q.TI
NR, NT = len(REBAL), len(TICK)
rb = REBAL.values.astype("datetime64[ns]")

ITEMS = list(F.FLOW) + list(F.INSTANT) + ["shares"]
PRIOR = ["assets", "rev", "ni", "shares", "equity", "liab", "gp", "oi"]  # 1년 전 값도 필요한 것

panel = {k: np.full((NR, NT), np.nan) for k in ITEMS}
for k in PRIOR:
    panel[k + "_1y"] = np.full((NR, NT), np.nan)
endinfo = np.full((NR, NT), np.datetime64("NaT"), dtype="datetime64[ns]")

t0 = time.time()
done = missing = 0
for n, (t, c) in enumerate(cik.items()):
    fn = f"CIK{int(c):010d}.json"
    if fn not in names or t not in TI:
        missing += 1
        continue
    try:
        cf = json.loads(z.read(fn))
        p = F.parse(cf)
    except Exception as e:
        missing += 1
        continue
    j = TI[t]
    for k in ITEMS:
        v, e = F.pit(p[k], rb)
        panel[k][:, j] = v
        if k == "ni":
            endinfo[:, j] = e
        if k in PRIOR:
            e1 = e - np.timedelta64(365, "D")
            panel[k + "_1y"][:, j] = F.value_at_end(p[k], e1, rb)
    done += 1
    if (n + 1) % 100 == 0:
        print(f"  {n+1}/{len(cik)}  {time.time()-t0:.0f}초", flush=True)

print(f"완료: 해석 {done}개, 실패·없음 {missing}개, {time.time()-t0:.0f}초")
pd.to_pickle({"panel": panel, "end": endinfo}, "fpanel.pkl")

# 보유율: 후보 종목 중 핵심 값(순이익·자산·주식수)이 있는 비율
core = np.isfinite(panel["ni"]) & np.isfinite(panel["assets"]) & np.isfinite(panel["shares"])
cov = (core & Q.ELIGM).sum(1) / np.maximum(Q.ELIGM.sum(1), 1)
s = pd.Series(cov, index=REBAL)
print("재조정일 기준 재무 데이터 보유율(후보 종목 중):")
print("  " + "  ".join(f"{y}:{v:.0%}" for y, v in s.resample("YE").mean().items() if y.year % 2 == 0))
lag = (REBAL.values.astype("datetime64[ns]")[:, None] - endinfo) / np.timedelta64(1, "D")
lag = np.where(np.isfinite(panel["ni"]), lag, np.nan)
print(f"재조정일과 최근 재무 기간 끝 사이의 시차: 중앙값 {np.nanmedian(lag):.0f}일, 90% 지점 {np.nanpercentile(lag, 90):.0f}일")
