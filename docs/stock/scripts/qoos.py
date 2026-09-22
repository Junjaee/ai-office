"""규칙 전략의 (1) 앞→뒤 기간 선택 시험 (2) 비용 민감도 (3) 저가주 효과가 생존편향인지 검증."""
import warnings

warnings.filterwarnings("ignore")
import itertools
import time

import numpy as np
import pandas as pd

import qengine as Q
import qsweep as S

pd.set_option("display.width", 250)
TR = ("2006-01-01", "2015-12-31")
TE = ("2016-01-01", None)

grid = list(itertools.product(S.Z.keys(), [1, -1], [10, 20, 30, 50],
                              ["equal", "invvol"], [False, True], [1, 3]))
print(f"== 1. 앞 기간(2006~2015)에서 고르고 뒤 기간(2016~2026)에서 시험 — 전략 {len(grid)}개 ==")
rows = []
t0 = time.time()
for sig, sgn, n, w, mf, re in grid:
    sc = S.Z[sig] * sgn
    a = Q.backtest(sc, n=n, weight=w, cost=0.0015, mkt_filter=mf, rebal_every=re,
                   start=TR[0], end=TR[1])
    b = Q.backtest(sc, n=n, weight=w, cost=0.0015, mkt_filter=mf, rebal_every=re,
                   start=TE[0], end=TE[1])
    if a is None or b is None:
        continue
    rows.append(dict(신호=sig, 방향=sgn, 보유수=n, 가중=w, 필터=mf, 재조정=re,
                     앞CAGR=a["CAGR"], 앞샤프=a["샤프"], 뒤CAGR=b["CAGR"], 뒤샤프=b["샤프"],
                     뒤낙폭=b["낙폭"], 회전율=b["회전율"]))
d = pd.DataFrame(rows)
d.to_pickle("qoos.pkl")
bt = Q.bench(start=TR[0], end=TR[1])["SPY 그냥 보유"]
be = Q.bench(start=TE[0], end=TE[1])["SPY 그냥 보유"]
print(f"  기준 SPY: 앞 {bt['CAGR']:.1%}(샤프 {bt['샤프']:.2f}) / 뒤 {be['CAGR']:.1%}(샤프 {be['샤프']:.2f})")
from scipy import stats

print(f"  앞·뒤 샤프 순위상관: {stats.spearmanr(d.앞샤프, d.뒤샤프).statistic:+.3f}   "
      f"앞·뒤 CAGR 순위상관: {stats.spearmanr(d.앞CAGR, d.뒤CAGR).statistic:+.3f}")
d["뒤순위"] = d.뒤샤프.rank(pct=True)
for k in (1, 5, 20, 100):
    t = d.nlargest(k, "앞샤프")
    print(f"  앞에서 샤프 상위 {k:3d}개 → 뒤 기간 샤프 순위 중앙값 {t.뒤순위.median():.0%}, "
          f"뒤 CAGR 중앙값 {t.뒤CAGR.median():.1%}, SPY를 이긴 비율 {(t.뒤CAGR>be['CAGR']).mean():.0%}")
print(f"  (전체 평균) 뒤 CAGR 중앙값 {d.뒤CAGR.median():.1%}, SPY를 이긴 비율 {(d.뒤CAGR>be['CAGR']).mean():.0%}")
print("\n  앞 기간 샤프 상위 5개의 실제 성적:")
print(d.nlargest(5, "앞샤프")[["신호", "방향", "보유수", "가중", "필터", "앞CAGR", "앞샤프", "뒤CAGR", "뒤샤프"]]
      .to_string(index=False, formatters={"앞CAGR": "{:.1%}".format, "뒤CAGR": "{:.1%}".format,
                                          "앞샤프": "{:.2f}".format, "뒤샤프": "{:.2f}".format}))

print(f"\n== 2. 비용 민감도 (회전율이 높은 전략은 실제 수수료에서 무너지는가) ==")
tests = [("모멘텀12-1", 1, 20, "equal", False, 1), ("잔차모멘텀", 1, 20, "invvol", False, 3),
         ("거래대금", 1, 50, "invvol", False, 3), ("저변동성252", 1, 30, "equal", False, 3),
         ("복합:4요소", 1, 20, "equal", False, 1), ("단기반전1개월", 1, 20, "equal", False, 1)]
out = []
for sig, sgn, n, w, mf, re in tests:
    row = {"전략": f"{sig} 상위{n} {w} {re}개월"}
    for c in (0.0, 0.0005, 0.0015, 0.0025, 0.005):
        r = Q.backtest(S.Z[sig] * sgn, n=n, weight=w, cost=c, mkt_filter=mf,
                       rebal_every=re, start=TE[0], end=TE[1])
        row[f"비용{c*100:.2f}%"] = f"{r['CAGR']:.1%}"
        row["회전율"] = f"{r['회전율']:.0%}"
    out.append(row)
print(pd.DataFrame(out).to_string(index=False))
print(f"  (참고) 같은 기간 SPY {be['CAGR']:.1%}. 미래에셋 온라인 수수료는 편도 0.25% 수준")

print("\n== 3. '저가주' 성적은 생존편향인가 ==")
cov = []
for t in Q.REBAL:
    memall = Q._cur if t > Q._last else Q._mem.loc[t]
    cov.append(len(Q.ELIG[t]) / max(len(memall), 1))
cov = pd.Series(cov, index=Q.REBAL)
for lab, st, en in [("2006~2010 (시세보유율 %.0f%%)" % (cov["2006":"2010"].mean() * 100), "2006-01-01", "2010-12-31"),
                    ("2011~2015 (%.0f%%)" % (cov["2011":"2015"].mean() * 100), "2011-01-01", "2015-12-31"),
                    ("2016~2020 (%.0f%%)" % (cov["2016":"2020"].mean() * 100), "2016-01-01", "2020-12-31"),
                    ("2021~2026 (%.0f%%)" % (cov["2021":].mean() * 100), "2021-01-01", None)]:
    r = Q.backtest(S.Z["가격"], n=20, weight="equal", cost=0.0015, mkt_filter=False, start=st, end=en)
    rb = Q.backtest(S.Z["모멘텀12-1"], n=20, weight="equal", cost=0.0015, start=st, end=en)
    sp = Q.bench(start=st, end=en)["SPY 그냥 보유"]
    print(f"  {lab:26s} 저가주 {r['CAGR']:6.1%} | 모멘텀 {rb['CAGR']:6.1%} | SPY {sp['CAGR']:6.1%}")
print("  시세 보유율이 낮은 초기일수록 저가주가 SPY 를 크게 이긴다면, 그것은 '망한 저가주가 데이터에 없기 때문'이다.")
