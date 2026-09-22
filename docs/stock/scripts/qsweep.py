"""규칙 기반 퀀트 전략 대량 백테스트."""
import warnings

warnings.filterwarnings("ignore")
import itertools
import time

import numpy as np
import pandas as pd

import qengine as Q

R = Q.REBAL
NT = len(Q.TICK)


def zmat(df):
    """재조정일별 횡단면 표준화 (종목 간 비교 가능하게)"""
    a = df.reindex(index=R, columns=Q.TICK).values.astype(float)
    a = np.where(Q.ELIGM, a, np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True)
    sd = np.nanstd(a, axis=1, keepdims=True)
    z = (a - mu) / np.where(sd > 0, sd, np.nan)
    return np.clip(z, -3, 3)


Z = {k: zmat(v) for k, v in Q.SIG.items()}

COMBO = {
    "복합:모멘텀+저변동성": ["모멘텀12-1", "저변동성252"],
    "복합:모멘텀+추세": ["모멘텀12-1", "200일선위"],
    "복합:모멘텀+반전": ["모멘텀12-1", "단기반전1개월"],
    "복합:저변동성+저베타": ["저변동성252", "저베타"],
    "복합:모멘텀+신고가+저변동성": ["모멘텀12-1", "52주신고가근접", "저변동성252"],
    "복합:4요소": ["모멘텀12-1", "저변동성252", "52주신고가근접", "단기반전1개월"],
}
for k, parts in COMBO.items():
    Z[k] = np.nanmean([Z[p] for p in parts], axis=0)

PERIODS = {"전체 2006~2026": (None, None), "2016~2026(시세보유율 91%)": ("2016-01-01", None)}


def main():
    rows = []
    t0 = time.time()
    grid = list(itertools.product(Z.keys(), [1, -1], [10, 20, 30, 50],
                                 ["equal", "invvol"], [False, True], [1, 3]))
    print(f"조건 {len(grid)}개 × 기간 {len(PERIODS)}개 = {len(grid)*len(PERIODS)} 백테스트", flush=True)
    for c, (sig, sgn, n, w, mf, re) in enumerate(grid):
        sc = Z[sig] * sgn
        for pn, (st, en) in PERIODS.items():
            r = Q.backtest(sc, n=n, weight=w, cost=0.0015, mkt_filter=mf,
                           rebal_every=re, start=st, end=en)
            if r is None:
                continue
            r.pop("곡선")
            rows.append(dict(신호=sig, 방향="높은쪽" if sgn > 0 else "낮은쪽", 보유수=n,
                             가중=w, 시장필터=mf, 재조정=f"{re}개월", 기간=pn, **r))
        if (c + 1) % 200 == 0:
            print(f"  {c+1}/{len(grid)}  {time.time()-t0:.0f}초", flush=True)
    df = pd.DataFrame(rows)
    df.to_pickle("qsweep.pkl")
    print(f"완료 {len(df)}행 {time.time()-t0:.0f}초")

    for pn in PERIODS:
        b = Q.bench(start=PERIODS[pn][0], end=PERIODS[pn][1])
        print(f"\n===== {pn} =====")
        print(f"  기준 SPY: {b['SPY 그냥 보유']['CAGR']:.2%} / 낙폭 {b['SPY 그냥 보유']['낙폭']:.0%} "
              f"/ 샤프 {b['SPY 그냥 보유']['샤프']:.2f}")
        print(f"  기준 동일가중: {b['지수 동일가중']['CAGR']:.2%} / 낙폭 {b['지수 동일가중']['낙폭']:.0%} "
              f"/ 샤프 {b['지수 동일가중']['샤프']:.2f}")
        d = df[df.기간 == pn]
        sp = b["SPY 그냥 보유"]["CAGR"]
        print(f"  전략 {len(d)}개 중 SPY 를 이긴 비율: {(d.CAGR>sp).mean():.0%}, "
              f"샤프가 SPY 보다 높은 비율: {(d.샤프>b['SPY 그냥 보유']['샤프']).mean():.0%}")
        top = d.nlargest(12, "샤프")
        print(top[["신호", "방향", "보유수", "가중", "시장필터", "재조정", "CAGR", "변동성",
                   "낙폭", "샤프", "회전율"]].to_string(index=False,
              formatters={"CAGR": "{:.1%}".format, "변동성": "{:.1%}".format,
                          "낙폭": "{:.0%}".format, "샤프": "{:.2f}".format,
                          "회전율": "{:.0%}".format}))


if __name__ == "__main__":
    main()
