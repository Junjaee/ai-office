"""퀀트 종목선택 백테스트 엔진.

원칙
- 그날 실제로 S&P500 에 있던 종목만 후보(상장폐지·피인수 종목 포함) → 생존 편향 축소
- 신호는 t일 종가로 계산, 매매는 t+1일 시가에 체결
- 규칙·머신러닝·딥러닝 모두 '점수 행렬' 하나만 바꿔 같은 엔진으로 돌린다
"""
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

# ── 데이터 ──────────────────────────────────────────────
_full = pd.read_pickle("px_full.pkl")
CLOSE, OPEN, VOL = _full["Close"], _full["Open"], _full["Volume"]
SPY = CLOSE["SPY"].dropna()
DAYS = SPY.index
CLOSE, OPEN, VOL = CLOSE.reindex(DAYS), OPEN.reindex(DAYS), VOL.reindex(DAYS)
BENCH = ["SPY", "^VIX", "KRW=X", "^GSPC"]
TICK = [c for c in CLOSE.columns if c not in BENCH]
PX, OP, VL = CLOSE[TICK], OPEN[TICK], VOL[TICK]
RET = PX.pct_change()
SPYR = SPY.pct_change()

_hist = pd.read_pickle("members.pkl")
_mem = _hist.reindex(DAYS, method="ffill")
_last = _hist.index[-1]
_cur = _hist.iloc[-1]
MEMBER = pd.DataFrame(False, index=DAYS, columns=TICK)
for i, d in enumerate(DAYS):
    s = _cur if d > _last else _mem.iloc[i]
    if isinstance(s, set):
        MEMBER.iloc[i] = [t in s for t in TICK]

# 월말 재조정일
_me = pd.Series(DAYS, index=DAYS).groupby([DAYS.year, DAYS.month]).max().values
REBAL = pd.DatetimeIndex(_me)
REBAL = REBAL[(REBAL >= DAYS[260]) & (REBAL < DAYS[-2])]


def _mdd(a):
    return (a / np.maximum.accumulate(a, axis=0) - 1).min(axis=0)


def signals():
    """t일까지의 정보만으로 만든 신호들. 값이 클수록 '좋다'는 방향으로 통일."""
    S = {}
    p = PX
    S["모멘텀12-1"] = p.shift(21) / p.shift(252) - 1
    S["모멘텀6-1"] = p.shift(21) / p.shift(126) - 1
    S["모멘텀3-1"] = p.shift(21) / p.shift(63) - 1
    S["모멘텀12-0"] = p / p.shift(252) - 1
    S["단기반전1개월"] = -(p / p.shift(21) - 1)
    S["단기반전1주"] = -(p / p.shift(5) - 1)
    v60 = RET.rolling(60).std()
    v252 = RET.rolling(252).std()
    S["저변동성60"] = -v60
    S["저변동성252"] = -v252
    cov = RET.rolling(252).cov(SPYR)
    beta = cov.div(SPYR.rolling(252).var(), axis=0)
    S["저베타"] = -beta
    S["고베타"] = beta
    mkt = SPY.shift(21) / SPY.shift(252) - 1
    S["잔차모멘텀"] = S["모멘텀12-1"] - beta.mul(mkt, axis=0)
    S["52주신고가근접"] = p / p.rolling(252).max()
    S["200일선위"] = p / p.rolling(200).mean() - 1
    S["위험조정모멘텀"] = S["모멘텀12-1"] / v252.replace(0, np.nan)
    dv = (p * VL).rolling(20).mean()
    S["거래대금"] = np.log(dv.replace(0, np.nan))
    S["거래대금증가"] = np.log((dv / (p * VL).rolling(252).mean()).replace(0, np.nan))
    roll = p.rolling(252)
    S["최대낙폭작음"] = -(1 - p / roll.max())
    S["가격"] = -np.log(p)  # 저가주
    S["변동성감소"] = -(v60 - v252)
    return S


SIG = signals()


def eligible(t):
    """t일에 지수 구성종목이면서 시세·거래가 살아 있는 종목"""
    i = DAYS.get_loc(t)
    ok = MEMBER.loc[t].values & PX.loc[t].notna().values & OP.iloc[i + 1].notna().values
    ok &= (PX.iloc[max(0, i - 252):i + 1].notna().sum().values > 200)
    ok &= (VL.iloc[i - 20:i + 1].mean().values > 0)
    return np.array(TICK)[ok]


ELIG = {t: eligible(t) for t in REBAL}


# ── 속도용 numpy 준비 ─────────────────────────────────
TI = {t: i for i, t in enumerate(TICK)}
OPa = OP.values
PXf = PX.ffill().values
RETa = RET.values
RIDX = np.array([DAYS.get_loc(t) for t in REBAL])
ELIGM = np.zeros((len(REBAL), len(TICK)), dtype=bool)
for k, t in enumerate(REBAL):
    ELIGM[k, [TI[x] for x in ELIG[t]]] = True
SPYa = SPY.values
SPYMA = SPY.rolling(200).mean().values
VOL60 = RET.rolling(60).std().values


def backtest(score, n=20, weight="equal", cost=0.0015, mkt_filter=False,
             rebal_every=1, start=None, end=None):
    """score: DataFrame(재조정일 × 종목) 또는 ndarray(재조정수 × 종목). 큰 값부터 고른다."""
    if isinstance(score, pd.DataFrame):
        sc_all = score.reindex(index=REBAL, columns=TICK).values
    else:
        sc_all = np.asarray(score, dtype=float)
    ks = np.arange(len(REBAL))
    if start is not None:
        ks = ks[REBAL[ks] >= pd.Timestamp(start)]
    if end is not None:
        ks = ks[REBAL[ks] <= pd.Timestamp(end)]
    ks = ks[::rebal_every]
    if len(ks) < 8:
        return None
    eq = np.empty(len(ks)); eq[0] = 1.0
    prev = np.zeros(len(TICK)); turn = []; holds = []
    for j in range(len(ks) - 1):
        k, k2 = ks[j], ks[j + 1]
        i, i2 = RIDX[k], RIDX[k2]
        sc = np.where(ELIGM[k] & np.isfinite(sc_all[k]) & np.isfinite(OPa[i + 1]), sc_all[k], -np.inf)
        m = int(np.isfinite(sc).sum())
        cash = mkt_filter and (SPYa[i] < SPYMA[i])
        cur = np.zeros(len(TICK))
        if m >= 5 and not cash:
            nn = min(n, m)
            pick = np.argpartition(-sc, nn - 1)[:nn]
            if weight == "invvol":
                v = VOL60[i, pick]
                w = np.where(np.isfinite(v) & (v > 0), 1 / np.maximum(v, 1e-6), 0.0)
                w = w / w.sum() if w.sum() > 0 else np.full(nn, 1 / nn)
            else:
                w = np.full(nn, 1 / nn)
            cur[pick] = w
        to = float(np.abs(cur - prev).sum())
        turn.append(to)
        val = eq[j] * (1 - cost * to)
        act = np.flatnonzero(cur)
        if len(act):
            o = OPa[i + 1, act]
            o2 = OPa[i2 + 1, act]
            last = PXf[i2 + 1, act]
            gr = np.where(np.isfinite(o2) & (o2 > 0), o2 / o, last / o)
            gr = np.where(np.isfinite(gr) & (gr > 0), gr, 1.0)
            val *= float((cur[act] * gr).sum())
            holds.append(len(act))
        eq[j + 1] = val
        prev = cur
    s = pd.Series(eq, index=REBAL[ks])
    r = s.pct_change().dropna()
    yrs = max((s.index[-1] - s.index[0]).days / 365.25, 0.1)
    mo = 12 / rebal_every
    return dict(배수=float(s.iloc[-1]), CAGR=float(s.iloc[-1]) ** (1 / yrs) - 1,
                변동성=float(r.std() * np.sqrt(mo)), 낙폭=float((s / s.cummax() - 1).min()),
                샤프=float((r.mean() * mo) / (r.std() * np.sqrt(mo) + 1e-12)),
                회전율=float(np.mean(turn)), 종목수=float(np.mean(holds)) if holds else 0.0,
                곡선=s)


def bench(start=None, end=None, cost=0.0015):
    rb = [t for t in REBAL if (start is None or t >= pd.Timestamp(start))
          and (end is None or t <= pd.Timestamp(end))]
    i0, i1 = DAYS.get_loc(rb[0]), DAYS.get_loc(rb[-1])
    s = SPY.iloc[i0:i1 + 1] / SPY.iloc[i0]
    r = s.pct_change().dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    out = {"SPY 그냥 보유": dict(배수=s.iloc[-1], CAGR=s.iloc[-1] ** (1 / yrs) - 1,
                            변동성=r.std() * np.sqrt(252), 낙폭=float((s / s.cummax() - 1).min()),
                            샤프=(r.mean() * 252) / (r.std() * np.sqrt(252)), 회전율=0.0, 종목수=1)}
    out["지수 동일가중"] = backtest(np.zeros((len(REBAL), len(TICK))), n=10000, cost=cost, start=start, end=end)
    return out


if __name__ == "__main__":
    print(f"종목 {len(TICK)}개, 거래일 {len(DAYS)}, 재조정 {len(REBAL)}회 "
          f"({REBAL[0].date()}~{REBAL[-1].date()})")
    print(f"후보 종목 수: 평균 {np.mean([len(v) for v in ELIG.values()]):.0f}개 "
          f"(최소 {min(len(v) for v in ELIG.values())}, 최대 {max(len(v) for v in ELIG.values())})")
    end_cnt = sum(1 for t in TICK if PX[t].last_valid_index() is not None
                  and PX[t].last_valid_index() < DAYS[-5])
    print(f"중간에 사라진 종목(상장폐지·피인수): {end_cnt}개")
    b = bench()
    for k, v in b.items():
        print(f"  {k:12s} {v['배수']:6.2f}배 CAGR {v['CAGR']:6.2%} 낙폭 {v['낙폭']:6.1%} 샤프 {v['샤프']:.2f}")
    sc = pd.DataFrame({t: SIG["모멘텀12-1"].loc[t] for t in REBAL}).T
    r = backtest(sc, n=20)
    print(f"  {'모멘텀 상위20':12s} {r['배수']:6.2f}배 CAGR {r['CAGR']:6.2%} 낙폭 {r['낙폭']:6.1%} "
          f"샤프 {r['샤프']:.2f} 회전율 {r['회전율']:.0%}")
