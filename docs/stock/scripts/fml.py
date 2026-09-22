"""재무 + 가격 특징으로 머신러닝·딥러닝. 특징 묶음을 바꿔 가며(재무만 / 가격만 / 둘 다) 비교."""
import time

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge

import ffactors as FF
import qengine as Q
import qpanel as P

torch.set_num_threads(12)
RNG = np.random.default_rng(0)
NR, NT = P.NR, P.NT
TEST_YEARS = list(range(2013, 2027))
PURGE = 2

FUND_KEYS = [k for k in FF.Z if not k.startswith("복합")]
XF = np.stack([np.nan_to_num(FF.Z[k], nan=0.0) for k in FUND_KEYS], axis=2).astype(np.float32)
XP = P.X
XB = np.concatenate([XP, XF], axis=2)
VALID = P.VALID & np.isfinite(FF.RAW["E/P"]) & np.isfinite(FF.RAW["ROA"])
SETS = {"가격 19": XP, "재무 %d" % len(FUND_KEYS): XF, "가격+재무 %d" % XB.shape[2]: XB}


class MLP(nn.Module):
    def __init__(s, d):
        super().__init__()
        s.f = nn.Sequential(nn.Linear(d, 96), nn.ReLU(), nn.Dropout(0.3), nn.Linear(96, 32), nn.ReLU(),
                            nn.Dropout(0.3), nn.Linear(32, 1))

    def forward(s, x):
        return s.f(x).squeeze(-1)


def train_torch(model, Xtr, ytr, epochs=30, bs=1024):
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    lossf = nn.MSELoss()
    idx = RNG.permutation(len(ytr))
    cut = int(len(idx) * 0.85)
    tr, va = idx[:cut], idx[cut:]
    best, bstate, bad = 1e9, None, 0
    for _ in range(epochs):
        model.train()
        for b in range(0, len(tr), bs):
            j = tr[b:b + bs]
            opt.zero_grad()
            loss = lossf(model(Xtr[j]), ytr[j])
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            v = float(lossf(model(Xtr[va]), ytr[va]))
        if v < best - 1e-5:
            best, bstate, bad = v, {k: t.clone() for k, t in model.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= 4:
                break
    if bstate:
        model.load_state_dict(bstate)
    return model


def run(name, X, every=1):
    pred = np.full((NR, NT), np.nan, dtype=np.float32)
    fitted, mdl = None, None
    for y in TEST_YEARS:
        te = np.where(P.YEARS == y)[0]
        tr = np.arange(0, te[0] - PURGE)
        tr = tr[P.YEARS[tr] >= 2010]
        if len(tr) < 30:
            continue
        if fitted is None or y - fitted >= every:
            m = VALID[tr]
            Xtr, ytr = X[tr][m], P.Y[tr][m]
            if name == "Ridge":
                mdl = Ridge(alpha=10.0).fit(Xtr, ytr)
            elif name == "부스팅":
                mdl = HistGradientBoostingRegressor(max_depth=4, max_iter=300, learning_rate=0.05, min_samples_leaf=200,
                                                    l2_regularization=1.0, random_state=0).fit(Xtr, ytr)
            elif name == "랜덤포레스트":
                mdl = RandomForestRegressor(n_estimators=150, max_depth=8, min_samples_leaf=100, n_jobs=12,
                                            random_state=0).fit(Xtr, ytr)
            else:
                mdl = train_torch(MLP(Xtr.shape[1]), torch.tensor(Xtr), torch.tensor(ytr))
            fitted = y
        for k in te:
            v = VALID[k]
            if v.sum() < 20:
                continue
            xk = X[k][v]
            if name == "신경망MLP":
                mdl.eval()
                with torch.no_grad():
                    pred[k, v] = mdl(torch.tensor(xk)).numpy()
            else:
                pred[k, v] = mdl.predict(xk)
    return pred


def ic_stats(pred):
    cc = []
    for k in range(NR):
        v = VALID[k] & np.isfinite(pred[k])
        if v.sum() < 30 or P.YEARS[k] < TEST_YEARS[0]:
            continue
        cc.append(np.corrcoef(pd.Series(pred[k, v]).rank(), pd.Series(P.FWD[k, v]).rank())[0, 1])
    cc = np.array(cc)
    return cc.mean(), cc.mean() / (cc.std() / np.sqrt(len(cc)))


if __name__ == "__main__":
    ST = f"{TEST_YEARS[0]}-01-01"
    b = Q.bench(start=ST, cost=0.0025)
    sp = b["SPY 그냥 보유"]
    print(f"시험 {ST}~2026: SPY {sp['CAGR']:.1%} 샤프 {sp['샤프']:.2f} 낙폭 {sp['낙폭']:.0%} | "
          f"동일가중 {b['지수 동일가중']['CAGR']:.1%} 샤프 {b['지수 동일가중']['샤프']:.2f}")
    print(f"학습 칸: {int(VALID[P.YEARS>=2010].sum()):,}개\n")
    rows = []
    preds = {}
    for sname, X in SETS.items():
        for mname, every in [("Ridge", 1), ("부스팅", 1), ("랜덤포레스트", 2), ("신경망MLP", 1)]:
            t0 = time.time()
            pr = run(mname, X, every)
            preds[(sname, mname)] = pr
            ic, t = ic_stats(pr)
            r20 = Q.backtest(pr, n=20, cost=0.0025, start=ST)
            r50 = Q.backtest(pr, n=50, cost=0.0025, rebal_every=3, start=ST)
            vol = r20["변동성"]
            rows.append(dict(특징=sname, 모델=mname, IC=ic, t값=t, 상위20_CAGR=r20["CAGR"], 상위20_샤프=r20["샤프"],
                             상위20_낙폭=r20["낙폭"], 같은변동성SPY=sp["샤프"] * vol, 상위50분기_CAGR=r50["CAGR"],
                             상위50분기_샤프=r50["샤프"], 회전율=r20["회전율"]))
            print(f"  {sname:12s} {mname:8s} IC {ic:+.4f} (t {t:+.2f}) | 상위20 CAGR {r20['CAGR']:6.1%} 샤프 {r20['샤프']:.2f} "
                  f"| 상위50·분기 {r50['CAGR']:6.1%} 샤프 {r50['샤프']:.2f} | {time.time()-t0:.0f}초", flush=True)
    df = pd.DataFrame(rows)
    pd.to_pickle({"rows": rows, "preds": preds}, "fml.pkl")
    print("\n" + df.to_string(index=False, formatters={
        "IC": "{:+.4f}".format, "t값": "{:+.2f}".format, "상위20_CAGR": "{:.1%}".format, "상위20_샤프": "{:.2f}".format,
        "상위20_낙폭": "{:.0%}".format, "같은변동성SPY": "{:.1%}".format, "상위50분기_CAGR": "{:.1%}".format,
        "상위50분기_샤프": "{:.2f}".format, "회전율": "{:.0%}".format}))
