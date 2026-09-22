"""갈아타기 전략 대규모 탐색: 격자 + 무작위 탐색을 세 기간과 앞/뒤 절반에서 전부 실행."""
import warnings

warnings.filterwarnings("ignore")
import itertools
import time

import numpy as np
import pandas as pd

import engine as E

RNG = np.random.default_rng(20260922)

DD_LEVELS = np.round(np.arange(0.05, 0.4501, 0.005), 3)
VIX_LEVELS = np.round(np.arange(20, 60.01, 0.5), 1)
CONFIRMS = [0, 20, 50, 100]
FRACS = [0.25, 0.5, 0.75, 1.0]
CAPS = [None, 0.05, 0.10, 0.15, 0.20, 0.25, 0.33]
TARGETS = [0.25, 0.4, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, None]
STOPS = [None, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6]
TRAILS = [None, 0.20, 0.25, 0.30, 0.40]
REARMS = [0.01, 0.02, 0.05, 0.10, 0.20]
MAXDAYS = [None, 126, 252, 504, 1008]
DESTS = ["L1", "L2", "L3"]


def core_grid():
    """격자 탐색: 곁가지를 끄고 주요 축만 전부 교차 → 조건별 효과를 깨끗하게 본다."""
    out = []
    ent = [("dd", x) for x in np.round(np.arange(0.05, 0.4001, 0.025), 3)]
    ent += [("vix", v) for v in np.arange(20, 56, 5.0)]
    for dest, (k, thr), cf, fr, cap, tg, st in itertools.product(
        DESTS, ent, [0, 50], [0.5, 1.0], [None, 0.15], [0.5, 1.0, 2.0, None], [None, 0.3, 0.45]
    ):
        out.append(dict(dest=dest, entry=k, thr=float(thr), confirm=cf, frac=fr, cap=cap,
                        target=tg, stop=st, trail=None, maxdays=None, rearm=0.05, 종류="격자"))
    return out


def random_search(n):
    out = []
    for _ in range(n):
        k = "dd" if RNG.random() < 0.6 else "vix"
        thr = float(RNG.choice(DD_LEVELS if k == "dd" else VIX_LEVELS))
        tg = TARGETS[RNG.integers(len(TARGETS))]
        st = STOPS[RNG.integers(len(STOPS))]
        tr = TRAILS[RNG.integers(len(TRAILS))]
        md = MAXDAYS[RNG.integers(len(MAXDAYS))]
        if tg is None and st is None and tr is None and md is None:
            tg = 1.0  # 청산 수단이 하나도 없으면 '안 팔고 보유'와 같아 중복
        out.append(dict(dest=DESTS[RNG.integers(3)], entry=k, thr=thr,
                        confirm=CONFIRMS[RNG.integers(4)], frac=FRACS[RNG.integers(4)],
                        cap=CAPS[RNG.integers(len(CAPS))], target=tg, stop=st, trail=tr,
                        maxdays=md, rearm=REARMS[RNG.integers(len(REARMS))], 종류="무작위"))
    return out


PERIODS = {"A": ("2011-11-01", None), "B": ("2006-07-01", None), "C": ("1999-04-01", None),
           "C1": ("1999-04-01", "2013-01-01"), "C2": ("2013-01-01", None),
           "B1": ("2006-07-01", "2016-07-01"), "B2": ("2016-07-01", None)}


def base_rows():
    rows = {}
    for p, (st, en) in PERIODS.items():
        rows[p] = {
            "①3등분": E.simulate(st, end=en),
            "②S&P만": E.simulate(st, end=en, static={1: 1.0}),
            "③나스닥만": E.simulate(st, end=en, static={2: 1.0}),
            "④늘2배": E.simulate(st, end=en, static={3: 1 / 3, 1: 1 / 3, 2: 1 / 3}),
            "⑤늘3배": E.simulate(st, end=en, dest="L3", static={3: 1 / 3, 1: 1 / 3, 2: 1 / 3}),
        }
    return rows


def main(n_random=34000):
    cfgs = core_grid() + random_search(n_random)
    print(f"조건 수: 격자 {sum(c['종류']=='격자' for c in cfgs)} + 무작위 {n_random} = {len(cfgs)}", flush=True)
    t0 = time.time()
    recs = []
    for i, c in enumerate(cfgs):
        kw = {k: v for k, v in c.items() if k != "종류"}
        row = dict(c)
        ok = True
        for p, (st, en) in PERIODS.items():
            r = E.simulate(st, end=en, **kw)
            row[f"배수_{p}"] = r["배수"]
            row[f"낙폭_{p}"] = r["낙폭"]
            row[f"노출_{p}"] = r["노출"]
            if p == "C":
                row["갈아탐"] = r["갈아탐"]
                row["손절"] = r["손절"]
                row["세금"] = r["세금"]
        if ok:
            recs.append(row)
        if (i + 1) % 5000 == 0:
            el = time.time() - t0
            print(f"  {i+1}/{len(cfgs)}  {el:.0f}초  (남은 예상 {el/(i+1)*(len(cfgs)-i-1):.0f}초)", flush=True)
    df = pd.DataFrame(recs)
    df.to_pickle("sweep.pkl")
    pd.to_pickle(base_rows(), "sweep_base.pkl")
    print(f"완료 {len(df)}행, {time.time()-t0:.0f}초")


if __name__ == "__main__":
    main()
