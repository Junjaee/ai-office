"""가치 팩터 결과가 진짜인지: 연도별, 시세 보유율 높은 기간만, 변동성 맞춤, 점수 뒤섞기 우연 시험."""
import numpy as np
import pandas as pd

import ffactors as FF
import qengine as Q

pd.set_option("display.width", 220)
RNG = np.random.default_rng(3)
CFG = dict(n=20, weight="invvol", cost=0.0025, rebal_every=3)
TESTS = {"복합:가치": FF.Z["복합:가치"], "FCF/P": FF.Z["FCF/P"], "주주환원": FF.Z["주주환원"],
         "E/P": FF.Z["E/P"], "복합:퀄리티": FF.Z["복합:퀄리티"]}

print("== 1. 시세 보유율이 높은 기간만 떼어 보기 ==")
for lab, st in [("2011~ (보유율 66→99%)", "2011-01-01"), ("2016~ (76→99%)", "2016-01-01"),
                ("2019~ (84→99%)", "2019-01-01"), ("2021~ (89→99%)", "2021-01-01"), ("2023~ (94→99%)", "2023-01-01")]:
    b = Q.bench(start=st, cost=0.0025)
    sp = b["SPY 그냥 보유"]
    line = f"  {lab:22s} SPY {sp['CAGR']:5.1%}/{sp['낙폭']:.0%}/샤프{sp['샤프']:.2f}"
    for k, z in TESTS.items():
        r = Q.backtest(z, start=st, **CFG)
        line += f" | {k} {r['CAGR']:5.1%}/{r['낙폭']:.0%}/{r['샤프']:.2f}"
    print(line)

print("\n== 2. 복합:가치 상위20 연도별 수익 vs SPY ==")
r = Q.backtest(FF.Z["복합:가치"], start="2011-01-01", **CFG)
cv = r["곡선"].resample("YE").last().pct_change().dropna()
sp = Q.SPY.reindex(r["곡선"].index).resample("YE").last().pct_change().dropna()
yy = pd.DataFrame({"가치": cv, "SPY": sp}).dropna()
yy["차이"] = yy.가치 - yy.SPY
print("  " + "  ".join(f"{d.year}: {a:+.0%}/{b:+.0%}" for d, a, b in zip(yy.index, yy.가치, yy.SPY)))
print(f"  SPY 를 이긴 해 {(yy.차이>0).sum()}/{len(yy)}, 진 해의 평균 차이 {yy[yy.차이<0].차이.mean():+.1%}, 최악의 해 차이 {yy.차이.min():+.1%}")
print(f"  변동성: 가치 {r['변동성']:.1%} vs SPY {Q.bench(start='2011-01-01')['SPY 그냥 보유']['변동성']:.1%} "
      f"→ 같은 변동성의 SPY 라면 {Q.bench(start='2011-01-01')['SPY 그냥 보유']['샤프']*r['변동성']:.1%} (가치 실제 {r['CAGR']:.1%})")

print("\n== 3. 우연 시험: 재무 점수를 매달 종목 사이에서 뒤섞어 200번 (신호는 없애고 나머지는 전부 같게) ==")
for k in ["복합:가치", "주주환원"]:
    z = FF.Z[k]
    real = Q.backtest(z, start="2011-01-01", **CFG)
    out = []
    for s in range(200):
        zz = z.copy()
        for row in range(zz.shape[0]):
            m = np.isfinite(zz[row])
            zz[row, m] = RNG.permutation(zz[row, m])
        rr = Q.backtest(zz, start="2011-01-01", **CFG)
        out.append((rr["CAGR"], rr["샤프"], rr["낙폭"]))
    a = np.array(out)
    print(f"  {k}: 실제 CAGR {real['CAGR']:.1%} 샤프 {real['샤프']:.2f} | 뒤섞은 200회: CAGR 중앙값 {np.median(a[:,0]):.1%} "
          f"(최고 {a[:,0].max():.1%}), 샤프 중앙값 {np.median(a[:,1]):.2f} (최고 {a[:,1].max():.2f}) "
          f"→ 실제만큼 좋은 경우 CAGR {(a[:,0]>=real['CAGR']).mean():.1%}, 샤프 {(a[:,1]>=real['샤프']).mean():.1%}")

print("\n== 4. 보유 종목 수·재조정 주기를 바꿔도 유지되나 (복합:가치, 2011~) ==")
rows = []
for n in (10, 20, 30, 50, 100):
    for re in (1, 3, 6, 12):
        r = Q.backtest(FF.Z["복합:가치"], n=n, weight="equal", cost=0.0025, rebal_every=re, start="2011-01-01")
        rows.append(dict(보유수=n, 재조정=f"{re}개월", CAGR=f"{r['CAGR']:.1%}", 샤프=f"{r['샤프']:.2f}", 낙폭=f"{r['낙폭']:.0%}", 회전율=f"{r['회전율']:.0%}"))
print(pd.DataFrame(rows).pivot(index="보유수", columns="재조정", values="CAGR").to_string())
print(pd.DataFrame(rows).pivot(index="보유수", columns="재조정", values="샤프").to_string())

print("\n== 5. 2011~2014(보유율 낮음)를 빼고 2015~ 만 ==")
for k, z in TESTS.items():
    r = Q.backtest(z, start="2015-01-01", **CFG)
    print(f"  {k:8s} {r['CAGR']:.1%} 낙폭 {r['낙폭']:.0%} 샤프 {r['샤프']:.2f}", end="")
sp = Q.bench(start="2015-01-01", cost=0.0025)["SPY 그냥 보유"]
print(f"\n  SPY      {sp['CAGR']:.1%} 낙폭 {sp['낙폭']:.0%} 샤프 {sp['샤프']:.2f}")
