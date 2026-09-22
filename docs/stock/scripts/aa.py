"""자산배분·시장타이밍 전략 백테스트 (ETF)."""
import warnings

warnings.filterwarnings("ignore")
import itertools

import numpy as np
import pandas as pd

D = pd.read_pickle("aa.pkl")
DAYS = D.index
RET = D.pct_change().fillna(0).values
COLS = list(D.columns)
CI = {c: i for i, c in enumerate(COLS)}
PX = D.values
ME = np.where(np.r_[DAYS.month[1:] != DAYS.month[:-1], True])[0]  # 월말 index
CASH = "BIL"


def mstat(eq, idx):
    s = pd.Series(eq, index=idx)
    r = s.pct_change().dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    return dict(배수=float(s.iloc[-1]), CAGR=float(s.iloc[-1]) ** (1 / yrs) - 1,
                변동성=float(r.std() * np.sqrt(252)), 낙폭=float((s / s.cummax() - 1).min()),
                샤프=float(r.mean() * 252 / (r.std() * np.sqrt(252) + 1e-12)))


def sim(wfun, start, end=None, cost=0.0015, every=1):
    """일별 곡선을 그대로 만들어 변동성·낙폭을 제대로 잰다."""
    i0 = int(np.searchsorted(DAYS, pd.Timestamp(start)))
    i1 = len(DAYS) - 1 if end is None else int(np.searchsorted(DAYS, pd.Timestamp(end)))
    rb = [m for m in ME if i0 <= m < i1 - 1][::every]
    if len(rb) < 12:
        return None
    eq = 1.0
    cur = np.zeros(len(COLS))
    vals = []
    days = []
    turn = []
    for j in range(len(rb) - 1):
        t, t2 = rb[j], rb[j + 1]
        w = wfun(t)
        if w is None:
            w = cur
        turn.append(float(np.abs(w - cur).sum()))
        eq *= (1 - cost * turn[-1])
        seg = RET[t + 1:t2 + 1]
        seg = np.where(np.isfinite(seg), seg, 0.0)
        path = np.cumprod(1 + seg, axis=0) @ w          # 매일의 포트폴리오 가치(비중 드리프트 반영)
        vals.append(eq * path)
        days.append(DAYS[t + 1:t2 + 1])
        gr = np.prod(1 + seg, axis=0)
        eq *= float((w * gr).sum())
        cur = w * gr / max(float((w * gr).sum()), 1e-12)
    curve = np.concatenate(vals)
    idx = pd.DatetimeIndex(np.concatenate([d.values for d in days]))
    st = mstat(curve, idx)
    st["회전율"] = float(np.mean(turn)) * (12 / every)
    return st


def ok(t, c, need=260):
    i = CI[c]
    return np.isfinite(PX[max(0, t - need):t + 1, i]).all() and PX[t, i] > 0


def mom(t, c, m):
    i = CI[c]
    j = max(0, t - 21 * m)
    return PX[t, i] / PX[j, i] - 1 if np.isfinite(PX[j, i]) and PX[j, i] > 0 else -np.inf


def above_ma(t, c, months):
    i = CI[c]
    w = PX[max(0, t - 21 * months):t + 1, i]
    w = w[np.isfinite(w)]
    return len(w) > 20 and PX[t, i] > w.mean()


def W(d):
    w = np.zeros(len(COLS))
    for k, v in d.items():
        w[CI[k]] = v
    return w


STRATS = {}
STRATS["① SPY 그냥 보유"] = lambda t: W({"SPY": 1})
STRATS["② 60/40 (SPY·IEF)"] = lambda t: W({"SPY": .6, "IEF": .4})
STRATS["③ 5자산 동일가중"] = lambda t: W({c: .2 for c in ["SPY", "EFA", "TLT", "GLD", "VNQ"] if ok(t, c)}) \
    if all(ok(t, c) for c in ["SPY", "EFA", "TLT", "GLD", "VNQ"]) else W({"SPY": 1})
STRATS["④ 올웨더 비슷"] = lambda t: W({"SPY": .30, "TLT": .40, "IEF": .15, "GLD": .075, "DBC": .075}) \
    if all(ok(t, c) for c in ["TLT", "IEF", "GLD", "DBC"]) else W({"SPY": 1})


def riskparity(t, assets=("SPY", "TLT", "GLD", "EFA")):
    av = [a for a in assets if ok(t, a)]
    if len(av) < 2:
        return W({"SPY": 1})
    v = np.array([RET[max(0, t - 120):t + 1, CI[a]].std() for a in av])
    w = (1 / np.maximum(v, 1e-6))
    return W(dict(zip(av, w / w.sum())))


STRATS["⑤ 위험균형(역변동성)"] = riskparity


def faber(t, months=10, asset="SPY"):
    return W({asset: 1}) if above_ma(t, asset, months) else W({CASH: 1} if ok(t, CASH, 20) else {"SHY": 1})


def gem(t, look=12):
    a, b = mom(t, "SPY", look), mom(t, "EFA", look) if ok(t, "EFA") else -np.inf
    cash_r = mom(t, "SHY", look) if ok(t, "SHY") else 0
    if max(a, b) <= cash_r:
        return W({"AGG": 1} if ok(t, "AGG") else {"SHY": 1})
    return W({"SPY": 1} if a >= b else {"EFA": 1})


def topk(t, pool, k, look, absfilter=True):
    av = [c for c in pool if ok(t, c)]
    if len(av) < k:
        return W({"SPY": 1})
    sc = sorted(av, key=lambda c: -mom(t, c, look))[:k]
    if absfilter:
        sc = [c for c in sc if mom(t, c, look) > 0]
    if not sc:
        return W({CASH: 1} if ok(t, CASH, 20) else {"SHY": 1})
    return W({c: 1 / len(sc) for c in sc})


def voltarget(t, target=0.10, asset="SPY"):
    v = RET[max(0, t - 60):t + 1, CI[asset]].std() * np.sqrt(252)
    lev = float(np.clip(target / max(v, 1e-6), 0, 1))
    return W({asset: lev, CASH: 1 - lev} if ok(t, CASH, 20) else {asset: lev, "SHY": 1 - lev})


SECTORS = ["XLK", "XLE", "XLF", "XLV", "XLI", "XLP", "XLU", "XLB", "XLY"]
ASSETS = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ", "LQD", "HYG"]

if __name__ == "__main__":
    rows = []
    PERIODS = {"2007~2026": "2007-01-01", "2016~2026": "2016-01-01"}
    grid = list(STRATS.items())
    for m in (6, 8, 10, 12):
        grid.append((f"⑥ 이동평균 타이밍 {m}개월", lambda t, m=m: faber(t, m)))
    for lk in (3, 6, 9, 12):
        grid.append((f"⑦ 듀얼모멘텀 {lk}개월", lambda t, lk=lk: gem(t, lk)))
    for k, lk in itertools.product((1, 2, 3, 4), (3, 6, 12)):
        grid.append((f"⑧ 섹터로테이션 상위{k} {lk}개월", lambda t, k=k, lk=lk: topk(t, SECTORS, k, lk)))
    for k, lk in itertools.product((1, 2, 3, 5), (3, 6, 12)):
        grid.append((f"⑨ 자산군 모멘텀 상위{k} {lk}개월", lambda t, k=k, lk=lk: topk(t, ASSETS, k, lk)))
    for tg in (0.08, 0.10, 0.12, 0.15):
        grid.append((f"⑩ 변동성목표 {tg:.0%}", lambda t, tg=tg: voltarget(t, tg)))
    print(f"전략 {len(grid)}개 × 기간 {len(PERIODS)} × 재조정 2 × 비용 2")
    for (nm, f), (pn, st), every, cost in itertools.product(grid, PERIODS.items(), (1, 3), (0.0015, 0.0025)):
        r = sim(f, st, cost=cost, every=every)
        if r:
            rows.append(dict(전략=nm, 기간=pn, 재조정=f"{every}개월", 비용=f"{cost*100:.2f}%", **r))
    df = pd.DataFrame(rows)
    df.to_pickle("aa_res.pkl")
    print(f"완료 {len(df)}행\n")
    for pn in PERIODS:
        d = df[(df.기간 == pn) & (df.비용 == "0.25%") & (df.재조정 == "1개월")]
        sp = d[d.전략 == "① SPY 그냥 보유"].iloc[0]
        print(f"===== {pn} (비용 0.25%, 월 재조정) — SPY: CAGR {sp.CAGR:.1%} 낙폭 {sp.낙폭:.0%} 샤프 {sp.샤프:.2f} =====")
        t = d.nlargest(14, "샤프")[["전략", "CAGR", "변동성", "낙폭", "샤프", "회전율"]]
        print(t.to_string(index=False, formatters={"CAGR": "{:.1%}".format, "변동성": "{:.1%}".format,
                                                   "낙폭": "{:.0%}".format, "샤프": "{:.2f}".format,
                                                   "회전율": "{:.0%}".format}))
        print(f"  전략 {len(d)}개 중 SPY 보다 샤프 높은 비율 {(d.샤프>sp.샤프).mean():.0%}, "
              f"CAGR 높은 비율 {(d.CAGR>sp.CAGR).mean():.0%}\n")
