"""재무 팩터 규칙 대량 백테스트 + 앞→뒤 기간 선택 시험 + 비용."""
import itertools
import time

import numpy as np
import pandas as pd
from scipy import stats

import ffactors as FF
import qengine as Q

pd.set_option("display.width", 250)
Z = FF.Z
PERIODS = {"2011~2026": ("2011-01-01", None), "2016~2026": ("2016-01-01", None)}
FMT = {"CAGR": "{:.1%}".format, "변동성": "{:.1%}".format, "낙폭": "{:.0%}".format,
       "샤프": "{:.2f}".format, "회전율": "{:.0%}".format}


def main():
    grid = list(itertools.product(Z.keys(), [1, -1], [10, 20, 30, 50], ["equal", "invvol"], [False, True], [1, 3]))
    print(f"조건 {len(grid)}개 × 기간 {len(PERIODS)}", flush=True)
    rows = []
    t0 = time.time()
    for sig, sgn, n, w, mf, re in grid:
        for pn, (st, en) in PERIODS.items():
            r = Q.backtest(Z[sig] * sgn, n=n, weight=w, cost=0.0025, mkt_filter=mf, rebal_every=re, start=st, end=en)
            if r is None:
                continue
            r.pop("곡선")
            rows.append(dict(팩터=sig, 방향="높은쪽" if sgn > 0 else "낮은쪽", 보유수=n, 가중=w,
                             시장필터=mf, 재조정=f"{re}개월", 기간=pn, **r))
    df = pd.DataFrame(rows)
    df.to_pickle("fsweep.pkl")
    print(f"완료 {len(df)}행 {time.time()-t0:.0f}초 (비용 편도 0.25%)")
    for pn, (st, en) in PERIODS.items():
        b = Q.bench(start=st, end=en, cost=0.0025)
        sp = b["SPY 그냥 보유"]
        d = df[df.기간 == pn]
        print(f"\n===== {pn} — SPY {sp['CAGR']:.1%} 낙폭 {sp['낙폭']:.0%} 샤프 {sp['샤프']:.2f} | "
              f"동일가중 {b['지수 동일가중']['CAGR']:.1%} 샤프 {b['지수 동일가중']['샤프']:.2f} =====")
        print(f"  {len(d)}개 중 SPY 보다 CAGR 높은 비율 {(d.CAGR>sp['CAGR']).mean():.0%}, 샤프 높은 비율 {(d.샤프>sp['샤프']).mean():.0%}")
        print(d.nlargest(12, "샤프")[["팩터", "방향", "보유수", "가중", "시장필터", "재조정", "CAGR", "낙폭", "샤프", "회전율"]]
              .to_string(index=False, formatters=FMT))
        print("  팩터별 중앙값(높은쪽만):")
        m = d[d.방향 == "높은쪽"].groupby("팩터")[["CAGR", "샤프", "낙폭"]].median().sort_values("샤프", ascending=False)
        print(m.head(12).to_string(formatters=FMT))

    print("\n== 앞 기간(2011~2018)에서 고르고 뒤 기간(2019~2026)에서 시험 ==")
    TR, TE = ("2011-01-01", "2018-12-31"), ("2019-01-01", None)
    rows = []
    for sig, sgn, n, w, mf, re in grid:
        a = Q.backtest(Z[sig] * sgn, n=n, weight=w, cost=0.0025, mkt_filter=mf, rebal_every=re, start=TR[0], end=TR[1])
        b = Q.backtest(Z[sig] * sgn, n=n, weight=w, cost=0.0025, mkt_filter=mf, rebal_every=re, start=TE[0], end=TE[1])
        if a and b:
            rows.append(dict(팩터=sig, 방향=sgn, 보유수=n, 가중=w, 필터=mf, 재조정=re, 앞CAGR=a["CAGR"], 앞샤프=a["샤프"],
                             뒤CAGR=b["CAGR"], 뒤샤프=b["샤프"], 뒤낙폭=b["낙폭"]))
    d = pd.DataFrame(rows)
    d.to_pickle("foos.pkl")
    bt = Q.bench(start=TR[0], end=TR[1], cost=0.0025)["SPY 그냥 보유"]
    be = Q.bench(start=TE[0], end=TE[1], cost=0.0025)["SPY 그냥 보유"]
    print(f"  SPY: 앞 {bt['CAGR']:.1%}(샤프 {bt['샤프']:.2f}) / 뒤 {be['CAGR']:.1%}(샤프 {be['샤프']:.2f})")
    print(f"  앞·뒤 샤프 순위상관 {stats.spearmanr(d.앞샤프, d.뒤샤프).statistic:+.3f}, CAGR 순위상관 {stats.spearmanr(d.앞CAGR, d.뒤CAGR).statistic:+.3f}")
    d["뒤순위"] = d.뒤샤프.rank(pct=True)
    for k in (1, 5, 20, 100):
        t = d.nlargest(k, "앞샤프")
        print(f"  앞 샤프 상위 {k:3d} → 뒤 샤프 순위 중앙값 {t.뒤순위.median():.0%}, 뒤 CAGR 중앙값 {t.뒤CAGR.median():.1%}, "
              f"뒤에서 SPY 이긴 비율 {(t.뒤CAGR>be['CAGR']).mean():.0%}, 샤프로 이긴 비율 {(t.뒤샤프>be['샤프']).mean():.0%}")
    print(f"  (전체) 뒤 CAGR 중앙값 {d.뒤CAGR.median():.1%}, SPY 이긴 비율 {(d.뒤CAGR>be['CAGR']).mean():.0%}")
    print("  앞 기간 샤프 상위 5:")
    print(d.nlargest(5, "앞샤프")[["팩터", "방향", "보유수", "가중", "필터", "앞CAGR", "앞샤프", "뒤CAGR", "뒤샤프"]]
          .to_string(index=False, formatters={"앞CAGR": "{:.1%}".format, "뒤CAGR": "{:.1%}".format, "앞샤프": "{:.2f}".format, "뒤샤프": "{:.2f}".format}))

    print("\n== 비용 민감도 (2016~2026) ==")
    out = []
    for sig in ["복합:가치", "복합:퀄리티", "복합:가치+퀄리티", "복합:마법공식", "주주환원", "복합:퀄리티+모멘텀"]:
        row = {"전략": f"{sig} 상위20 3개월"}
        for c in (0.0, 0.0015, 0.0025, 0.005):
            r = Q.backtest(Z[sig], n=20, cost=c, rebal_every=3, start="2016-01-01")
            row[f"비용{c*100:.2f}%"] = f"{r['CAGR']:.1%}"
            row["회전율"] = f"{r['회전율']:.0%}"
        out.append(row)
    print(pd.DataFrame(out).to_string(index=False))


if __name__ == "__main__":
    main()
