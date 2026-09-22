"""가치 전략의 섹터 쏠림과, 한국 양도세(22%)를 반영한 뒤의 성적."""
import numpy as np
import pandas as pd

import ffactors as FF
import qengine as Q

pd.set_option("display.width", 200)
CFG = dict(n=20, weight="invvol", cost=0.0025, rebal_every=3)

print("== 1. 복합:가치 상위20 이 어떤 업종에 몰리나 (현재 구성종목의 업종 기준) ==")
wiki = pd.read_csv("sp500_wiki.csv")
sec = {r.Symbol.replace(".", "-"): r._3 for r in wiki.itertuples()}  # GICS Sector
z = FF.Z["복합:가치"]
ks = [k for k in range(len(Q.REBAL)) if Q.REBAL[k].year >= 2011][::3]
hist = {}
for k in ks:
    sc = np.where(Q.ELIGM[k] & np.isfinite(z[k]), z[k], -np.inf)
    pick = np.argpartition(-sc, 19)[:20]
    for j in pick:
        s = sec.get(Q.TICK[j], "기타/사라진 회사")
        hist[s] = hist.get(s, 0) + 1
tot = sum(hist.values())
for s, c in sorted(hist.items(), key=lambda x: -x[1]):
    print(f"  {s:28s} {c/tot:5.1%}")
print("  (참고) 지수 전체 업종 비율 상위:", ", ".join(f"{s} {c/len(wiki):.0%}" for s, c in wiki.iloc[:, 2].value_counts().head(4).items()))
# 한 시점 최대 쏠림
mx = []
for k in ks:
    sc = np.where(Q.ELIGM[k] & np.isfinite(z[k]), z[k], -np.inf)
    pick = np.argpartition(-sc, 19)[:20]
    cnt = pd.Series([sec.get(Q.TICK[j], "기타") for j in pick]).value_counts()
    mx.append((Q.REBAL[k].date(), cnt.index[0], cnt.iloc[0]))
worst = max(mx, key=lambda x: x[2])
print(f"  한 시점 최대 쏠림: {worst[0]} {worst[1]} {worst[2]}/20 종목")

print("\n== 2. 한국 양도세 22% 반영 (보수적: 매년 이익 전부 실현으로 가정, 250만원 공제·환율 무시) ==")


def after_tax_curve(curve, realize_each_year=True):
    y = curve.resample("YE").last()
    y = pd.concat([curve.iloc[[0]], y]).drop_duplicates()
    if realize_each_year:
        v = 1.0
        for a, b in zip(y.values[:-1], y.values[1:]):
            g = b / a - 1
            v *= 1 + (g * 0.78 if g > 0 else g)
        return v
    g = y.values[-1] / y.values[0] - 1
    return 1 + g * 0.78


for st in ("2011-01-01", "2016-01-01", "2021-01-01"):
    r = Q.backtest(FF.Z["복합:가치"], start=st, **CFG)
    cv = r["곡선"]
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    sp = Q.SPY.reindex(cv.index)
    sp = sp / sp.iloc[0]
    v_pre, v_post = cv.iloc[-1], after_tax_curve(cv, True)
    s_pre, s_post = sp.iloc[-1], after_tax_curve(sp, False)   # SPY 는 끝에 한 번만 팔아 세금
    print(f"  {st[:4]}~ ({yrs:.0f}년): 가치 세전 {v_pre**(1/yrs)-1:.1%} → 세후 {v_post**(1/yrs)-1:.1%} | "
          f"SPY 세전 {s_pre**(1/yrs)-1:.1%} → 세후(끝에 매도) {s_post**(1/yrs)-1:.1%} | 세후 차이 {v_post**(1/yrs)-s_post**(1/yrs):+.1%}p")
print("  (가치 전략은 회전율 ~60%/분기라 이익 대부분이 1~2년 안에 실현됨. SPY 는 보유만 하면 팔 때까지 과세 이연.)")
