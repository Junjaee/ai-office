"""우연 시험: 가짜 시장을 여러 개 만들어 같은 탐색을 돌린다.

토막 재배열(block bootstrap)로 하루하루의 성질과 자산 간 관계는 유지하되,
'언제 사고팔면 좋은가' 하는 긴 흐름은 흐트러뜨린다.
그런 세상에서도 800개 중 1등이 크게 이긴다면, 진짜 세상의 1등도 실력의 증거가 못 된다.
"""
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

import engine as E
import sweep as S

RNG = np.random.default_rng(7)
BLOCK = 63
N_WORLDS = 150
N_CFG = 800

P0, VIX0 = E.P.copy(), E.VIX.copy()
COLS = ["DIV", "SP", "NQ", "L1", "L2", "L3"]
RET0 = np.log(P0[COLS]).diff().fillna(0).values
V0 = VIX0.values
IDX0 = P0.index
NN = len(IDX0)


def make_world():
    starts = RNG.integers(0, NN - BLOCK, size=NN // BLOCK + 1)
    order = np.concatenate([np.arange(s, s + BLOCK) for s in starts])[:NN]
    r = RET0[order]
    px = pd.DataFrame(np.exp(np.cumsum(r, axis=0)), index=IDX0, columns=COLS)
    vx = pd.Series(V0[order], index=IDX0)
    return px, vx


def run_set(cfgs, start):
    out = []
    for c in cfgs:
        kw = {k: v for k, v in c.items() if k != "종류"}
        try:
            out.append(E.simulate(start, **kw)["배수"])
        except Exception:
            out.append(np.nan)
    return np.array(out, dtype=float)


if __name__ == "__main__":
    cfgs = S.random_search(N_CFG)
    start = "1999-04-01"

    base_real = E.simulate(start)["배수"]
    real = run_set(cfgs, start)
    rr = real / base_real
    print(f"진짜 세상: 기준 {base_real:.2f}배 | 같은 {N_CFG}개 조건 중 1등 {np.nanmax(rr):.2f}배(기준 대비), "
          f"중앙값 {np.nanmedian(rr):.2f}, 기준을 이긴 비율 {np.nanmean(rr>1):.0%}")

    best, med, win = [], [], []
    for w in range(N_WORLDS):
        px, vx = make_world()
        E.rebind(px, vx)
        b = E.simulate(start)["배수"]
        v = run_set(cfgs, start) / b
        best.append(np.nanmax(v)); med.append(np.nanmedian(v)); win.append(np.nanmean(v > 1))
        if (w + 1) % 25 == 0:
            print(f"  가짜 세상 {w+1}/{N_WORLDS} 1등 중앙값 {np.median(best):.2f}", flush=True)
    E.rebind(P0, VIX0)
    best, med, win = map(np.array, (best, med, win))
    q = lambda a, p: np.quantile(a, p)
    print("\n가짜 세상 %d개 (긴 흐름이 없는, 즉 '타이밍 실력이 있을 수 없는' 세상)" % N_WORLDS)
    print(f"  1등의 기준 대비 배수: 중앙값 {np.median(best):.2f}, 90% 지점 {q(best,.9):.2f}, 최대 {best.max():.2f}")
    print(f"  중앙 조건의 기준 대비: 중앙값 {np.median(med):.2f}")
    print(f"  기준을 이긴 조건 비율: 중앙값 {np.median(win):.0%}")
    p_val = float((best >= np.nanmax(rr)).mean())
    print(f"\n진짜 세상의 1등({np.nanmax(rr):.2f}배)이 가짜 세상에서도 나올 확률 ≈ {p_val:.0%}")
    np.save("null_best.npy", best)
