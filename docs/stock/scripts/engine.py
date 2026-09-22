"""갈아타기 전략 대규모 탐색용 빠른 엔진.

사건(진입·청산·적립·연말세금)이 있는 날에만 계산하고 그 사이는 건너뛴다.
자산 index: 0=DIV(배당) 1=SP(S&P500) 2=NQ(나스닥100) 3=목적지(L1/L2/L3)
"""
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

COST, TAX = 0.003, 0.22


def load():
    d = pd.read_pickle("etf.pkl")

    def splice(new, old):
        r = d[new].pct_change().where(d[new].notna() & d[new].shift().notna(), d[old].pct_change())
        return (1 + r.fillna(0)).cumprod()

    rf = (d["^IRX"].ffill() / 100).fillna(0.02)
    d["SYN2"] = (1 + (2 * d["QQQ"].pct_change() - (0.0095 + rf) / 252).fillna(0)).cumprod()
    d["SYN3"] = (1 + (3 * d["QQQ"].pct_change() - (0.0086 + 2 * rf) / 252).fillna(0)).cumprod()
    P = pd.DataFrame(
        {
            "DIV": splice("SCHD", "VEIPX"),
            "SP": d["SPY"],
            "NQ": d["QQQ"],
            "L1": d["QQQ"],
            "L2": splice("QLD", "SYN2"),
            "L3": splice("TQQQ", "SYN3"),
        }
    )
    P = P[d["QQQ"].notna()]
    return P, d["^VIX"].reindex(P.index).ffill()


P, VIX = load()
IDX = P.index
N = len(IDX)
NQ = P["NQ"].values
HI = pd.Series(NQ, index=IDX).rolling(252, min_periods=1).max().values
DD = NQ / HI - 1
VIXV = VIX.values
MA = {m: pd.Series(NQ, index=IDX).rolling(m).mean().values for m in (20, 50, 100, 200)}
YEAR_END = np.where(np.r_[IDX.year[1:] != IDX.year[:-1], True])[0]
MONTH_1 = np.where(np.r_[True, IDX.month[1:] != IDX.month[:-1]])[0]
ASSETS = {k: P[["DIV", "SP", "NQ", k]].values for k in ("L1", "L2", "L3")}


def next_true(cond):
    """nt[t] = t 이상에서 cond 가 참인 첫 index (없으면 N)"""
    pos = np.where(np.asarray(cond), np.arange(N), N)
    suf = np.minimum.accumulate(pos[::-1])[::-1]
    return np.r_[suf, N].astype(np.int32)


def rebind(P_new, VIX_new):
    """가짜 시장(부트스트랩)으로 전역 시세를 갈아끼운다."""
    global P, VIX, IDX, N, NQ, HI, DD, VIXV, MA, YEAR_END, MONTH_1, ASSETS, _cache
    P, VIX = P_new, VIX_new
    IDX = P.index
    N = len(IDX)
    NQ = P["NQ"].values
    HI = pd.Series(NQ, index=IDX).rolling(252, min_periods=1).max().values
    DD = NQ / HI - 1
    VIXV = VIX.values
    MA = {m: pd.Series(NQ, index=IDX).rolling(m).mean().values for m in (20, 50, 100, 200)}
    YEAR_END = np.where(np.r_[IDX.year[1:] != IDX.year[:-1], True])[0]
    MONTH_1 = np.where(np.r_[True, IDX.month[1:] != IDX.month[:-1]])[0]
    ASSETS = {k: P[["DIV", "SP", "NQ", k]].values for k in ("L1", "L2", "L3")}
    _cache = {}


_cache = {}


def entry_nt(kind, thr, confirm):
    """kind: 'dd'(고점대비 하락) 또는 'vix'. confirm: 0(즉시) 또는 이동평균 일수(회복 확인)."""
    key = (kind, round(thr, 4), confirm)
    if key not in _cache:
        base = (DD <= -thr) if kind == "dd" else (VIXV >= thr)
        if confirm:
            seen = pd.Series(base, index=IDX).rolling(250, min_periods=1).max().values.astype(bool)
            cond = seen & (NQ > MA[confirm])
        else:
            cond = base
        _cache[key] = next_true(cond)
    return _cache[key]


def rearm_nt(r):
    key = ("re", round(r, 4))
    if key not in _cache:
        _cache[key] = next_true(DD >= -r)
    return _cache[key]


def first_ge(arr, t0, level):
    if t0 >= N:
        return N
    w = np.flatnonzero(arr[t0:] >= level)
    return N if w.size == 0 else t0 + int(w[0])


def first_le(arr, t0, level):
    if t0 >= N:
        return N
    w = np.flatnonzero(arr[t0:] <= level)
    return N if w.size == 0 else t0 + int(w[0])


def simulate(start, dest="L2", entry=None, thr=0.2, confirm=0, frac=1.0, rearm=0.05,
             cap=None, target=1.0, stop=None, trail=None, maxdays=None,
             lump=True, tax=True, static=None, lag=1, end=None):
    A = ASSETS[dest]
    s0 = int(IDX.searchsorted(pd.Timestamp(start)))
    last = N - 1 if end is None else int(IDX.searchsorted(pd.Timestamp(end))) - 1
    LEVP = A[:, 3]
    sh = np.zeros(4)
    cb = np.zeros(4)
    contrib = 0.0
    units = 0.0
    taxpaid = 0.0
    realized = 0.0
    ev_days = []
    ev_sh = []
    flows = []
    ntrade = 0
    nstop = 0
    log = []
    contrib_days = [s0] if lump else [int(x) for x in MONTH_1 if s0 <= x <= last]
    tax_days = [int(x) for x in YEAR_END if s0 <= x <= last] if tax else []
    w = static if static is not None else {0: 1 / 3, 1: 1 / 3, 2: 1 / 3}

    def buy(i, cash, t):
        sh[i] += cash * (1 - COST) / A[t, i]
        cb[i] += cash

    def sell(i, f, t):
        nonlocal realized
        v = sh[i] * A[t, i] * f
        realized += v - cb[i] * f
        cb[i] *= 1 - f
        sh[i] *= 1 - f
        return v * (1 - COST)

    ev_u = []

    def snap(t):
        ev_days.append(t)
        ev_sh.append(sh.copy())
        ev_u.append(units)

    armed = True
    inlev = False
    pend = ""
    ci = ti = 0
    entry_t = entry_nt(entry, thr, confirm)[s0] if entry else N
    exit_t = N
    guard = 0
    while True:
        guard += 1
        if guard > 5000:
            break
        cands = []
        if ci < len(contrib_days):
            cands.append(contrib_days[ci])
        if ti < len(tax_days):
            cands.append(tax_days[ti])
        if entry and not inlev and entry_t <= last:
            cands.append(entry_t)
        if inlev and exit_t <= last:
            cands.append(exit_t)
        if not cands:
            break
        t = min(cands)
        if ci < len(contrib_days) and contrib_days[ci] == t:
            amt = 100000.0 if lump else 1000.0
            pre = float(sh @ A[t])
            units += amt / (pre / units if units > 0 else 1.0)
            for i, wt in w.items():
                if wt > 0:
                    buy(i, amt * wt, t)
            contrib += amt
            flows.append((IDX[t], -amt))
            snap(t)
            ci += 1
        if ti < len(tax_days) and tax_days[ti] == t:
            if realized > 0:
                due = realized * TAX
                vals = sh * A[t]
                src = 0 if vals[0] > due else int(np.argmax(vals))
                if vals[src] > 0:
                    f = min(1.0, due / vals[src])
                    cb[src] *= 1 - f
                    sh[src] *= 1 - f
                    taxpaid += due
                snap(t)
            realized = 0.0
            ti += 1
        if entry and not inlev and entry_t == t:
            te = min(t + lag, last)
            total = float(sh @ A[te])
            have = sh[0] * A[te, 0]
            amt = have * frac
            if cap is not None:
                amt = min(amt, max(0.0, cap * total - sh[3] * A[te, 3]))
            if amt > 1e-9 and have > 0:
                buy(3, sell(0, amt / have, te), te)
                ntrade += 1
                snap(te)
                log.append(("갈아탐", IDX[te]))
                inlev = True
                armed = False
                avg = cb[3] / sh[3]
                a = first_ge(LEVP, te + 1, avg * (1 + target)) if target else N
                b = first_le(LEVP, te + 1, avg * (1 - stop)) if stop else N
                c = N
                if trail:
                    seg = LEVP[te:]
                    ww = np.flatnonzero(seg <= np.maximum.accumulate(seg) * (1 - trail))
                    ww = ww[ww > 0]
                    c = te + int(ww[0]) if ww.size else N
                dmax = te + maxdays if maxdays else N
                exit_t = min(a, b, c, dmax, N)
                pend = "청산" if exit_t == a else ("손절" if exit_t == b else ("추적손절" if exit_t == c else "시간청산"))
                entry_t = N
            else:
                entry_t = entry_nt(entry, thr, confirm)[min(t + 1, N)]
        elif inlev and exit_t == t:
            te = min(t + lag, last)
            if sh[3] > 0:
                buy(0, sell(3, 1.0, te), te)
                snap(te)
                log.append((pend, IDX[te]))
                nstop += pend != "청산"
            inlev = False
            exit_t = N
            ra = rearm_nt(rearm)[min(te + 1, N)]
            entry_t = entry_nt(entry, thr, confirm)[min(ra, N)] if entry else N
    ev_days.append(last + 1)
    ev_sh.append(sh.copy())
    ev_u.append(units)
    days = np.array(ev_days)
    shs = np.array(ev_sh)
    us = np.array(ev_u)
    order = np.argsort(days, kind="stable")
    days, shs, us = days[order], shs[order], us[order]
    keep = np.r_[np.diff(days) > 0, True]
    days, shs, us = days[keep], shs[keep], us[keep]
    # 보유량 shs[i] 는 days[i] 부터 days[i+1] 직전까지 유효하다(사건은 종가에 일어난다)
    counts = np.diff(days)
    eq = np.empty(0)
    expo = 0.0
    if len(counts) and counts.sum() > 0:
        repsh = np.repeat(shs[:-1], counts, axis=0)
        repu = np.repeat(np.maximum(us[:-1], 1e-9), counts)
        vals = repsh * A[days[0]:days[0] + repsh.shape[0]]
        tot = vals.sum(1)
        good = tot > 0
        expo = float((vals[good, 3] / tot[good]).mean()) if good.any() else 0.0
        eq = (tot / repu)[good]
    final = float(sh @ A[last])
    fl = flows + [(IDX[last], final)]
    ts = np.array([(a - fl[0][0]).days / 365.25 for a, _ in fl])
    cs = np.array([c for _, c in fl])
    lo, hi = -0.9, 2.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if (cs / (1 + mid) ** ts).sum() > 0 else (lo, mid)
    mdd = float((eq / np.maximum.accumulate(eq) - 1).min()) if len(eq) else 0.0
    return dict(배수=final / contrib, IRR=mid, 낙폭=mdd, 갈아탐=ntrade, 손절=nstop,
                세금=taxpaid / contrib, 노출=expo, 로그=log)


if __name__ == "__main__":
    import time

    chk = [("① 3등분만", dict()),
           ("대표 -20%/+100%", dict(entry="dd", thr=0.2, target=1.0)),
           ("손절 -30%", dict(entry="dd", thr=0.2, target=1.0, stop=0.3)),
           ("상한 15%", dict(entry="dd", thr=0.2, target=1.0, cap=0.15)),
           ("TQQQ", dict(entry="dd", thr=0.2, target=1.0, dest="L3")),
           ("QQQM", dict(entry="dd", thr=0.2, target=1.0, dest="L1")),
           ("VIX 35", dict(entry="vix", thr=35, target=1.0)),
           ("적립 대표", dict(entry="dd", thr=0.2, target=1.0, lump=False))]
    for nm, kw in chk:
        row = []
        for p, st in [("A", "2011-11-01"), ("B", "2006-07-01"), ("C", "1999-04-01")]:
            r = simulate(st, **kw)
            row.append(f"{p} {r['배수']:5.2f}/{r['낙폭']:4.0%}")
        print(f"{nm:16s}", " | ".join(row))
    t0 = time.time()
    for _ in range(300):
        simulate("1999-04-01", entry="dd", thr=0.2, target=1.0, stop=0.3)
    dt = (time.time() - t0) / 300
    print(f"\n1회 {dt*1000:.2f}ms → 10만회 {dt*100000/60:.1f}분")
