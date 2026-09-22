"""머신러닝·딥러닝으로 다음 달 유망 종목 고르기.

규칙: 학습은 과거만, 시험은 미래만. 정답이 한 달을 내다보므로 학습 끝과 시험 시작 사이를 두 달 비운다.
해마다 다시 학습하고, 그해 예측만 모아 같은 백테스트 엔진에 넣는다.
"""
import warnings

warnings.filterwarnings("ignore")
import time

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge

import qengine as Q
import qpanel as P

torch.set_num_threads(12)
RNG = np.random.default_rng(0)
NR, NT = P.NR, P.NT
TEST_YEARS = list(range(2011, 2027))
PURGE = 2


def slices(y):
    te = np.where(P.YEARS == y)[0]
    tr = np.arange(0, te[0] - PURGE)
    return tr, te


def flat(idx, seq=False):
    m = P.VALID[idx]
    xs = P.SEQ[idx][m] if seq else P.X[idx][m]
    return xs, P.Y[idx][m], m


class MLP(nn.Module):
    def __init__(s, d):
        super().__init__()
        s.f = nn.Sequential(nn.Linear(d, 64), nn.ReLU(), nn.Dropout(0.3),
                            nn.Linear(64, 32), nn.ReLU(), nn.Dropout(0.3), nn.Linear(32, 1))

    def forward(s, x): return s.f(x).squeeze(-1)


class CNN(nn.Module):
    def __init__(s, extra=0):
        super().__init__()
        s.c = nn.Sequential(nn.Conv1d(1, 16, 5, padding=2), nn.ReLU(), nn.MaxPool1d(2),
                            nn.Conv1d(16, 32, 5, padding=2), nn.ReLU(), nn.AdaptiveAvgPool1d(4))
        s.h = nn.Sequential(nn.Linear(32 * 4 + extra, 32), nn.ReLU(), nn.Dropout(0.3), nn.Linear(32, 1))
        s.extra = extra

    def forward(s, x, e=None):
        z = s.c(x.unsqueeze(1)).flatten(1)
        if s.extra:
            z = torch.cat([z, e], 1)
        return s.h(z).squeeze(-1)


class GRU(nn.Module):
    def __init__(s):
        super().__init__()
        s.g = nn.GRU(1, 24, batch_first=True)
        s.h = nn.Linear(24, 1)

    def forward(s, x):
        o, _ = s.g(x.unsqueeze(-1))
        return s.h(o[:, -1]).squeeze(-1)


def train_torch(model, Xtr, ytr, Xe=None, epochs=25, bs=1024, lr=1e-3):
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    lossf = nn.MSELoss()
    n = len(ytr)
    cut = int(n * 0.85)
    idx = RNG.permutation(n)
    tr, va = idx[:cut], idx[cut:]
    best, bstate, bad = 1e9, None, 0
    for ep in range(epochs):
        model.train()
        for b in range(0, len(tr), bs):
            j = tr[b:b + bs]
            opt.zero_grad()
            out = model(Xtr[j]) if Xe is None else model(Xtr[j], Xe[j])
            loss = lossf(out, ytr[j])
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            o = model(Xtr[va]) if Xe is None else model(Xtr[va], Xe[va])
            v = float(lossf(o, ytr[va]))
        if v < best - 1e-5:
            best, bstate, bad = v, {k: t.clone() for k, t in model.state_dict().items()}, 0
        else:
            bad += 1
            if bad >= 4:
                break
    if bstate:
        model.load_state_dict(bstate)
    return model


def run_model(name, every=1):
    pred = np.full((NR, NT), np.nan, dtype=np.float32)
    t0 = time.time()
    fitted = None
    for y in TEST_YEARS:
        tr, te = slices(y)
        if len(tr) < 48:
            continue
        need = (fitted is None) or ((y - fitted) >= every)
        if name in ("Ridge", "부스팅", "랜덤포레스트", "신경망MLP"):
            Xtr, ytr, _ = flat(tr)
            if need:
                if name == "Ridge":
                    mdl = Ridge(alpha=10.0).fit(Xtr, ytr)
                elif name == "부스팅":
                    mdl = HistGradientBoostingRegressor(max_depth=4, max_iter=300, learning_rate=0.05,
                                                        min_samples_leaf=200, l2_regularization=1.0,
                                                        random_state=0).fit(Xtr, ytr)
                elif name == "랜덤포레스트":
                    mdl = RandomForestRegressor(n_estimators=150, max_depth=8, min_samples_leaf=100,
                                                n_jobs=12, random_state=0).fit(Xtr, ytr)
                else:
                    m = MLP(Xtr.shape[1])
                    mdl = train_torch(m, torch.tensor(Xtr), torch.tensor(ytr))
                fitted = y
                run_model.cache = mdl
            mdl = run_model.cache
            for k in te:
                v = P.VALID[k]
                if v.sum() < 20:
                    continue
                xk = P.X[k][v]
                if name == "신경망MLP":
                    mdl.eval()
                    with torch.no_grad():
                        pred[k, v] = mdl(torch.tensor(xk)).numpy()
                else:
                    pred[k, v] = mdl.predict(xk)
        else:  # 순차 모델
            Str, ytr, _ = flat(tr, seq=True)
            sd = Str.std(axis=1, keepdims=True) + 1e-6
            Str = np.clip(Str / sd, -6, 6)
            if need:
                if name == "합성곱CNN":
                    m = CNN()
                    mdl = train_torch(m, torch.tensor(Str), torch.tensor(ytr), epochs=20)
                elif name == "순환신경망GRU":
                    m = GRU()
                    mdl = train_torch(m, torch.tensor(Str), torch.tensor(ytr), epochs=15, bs=2048)
                else:  # 혼합
                    Ftr, _, _ = flat(tr)
                    m = CNN(extra=Ftr.shape[1])
                    mdl = train_torch(m, torch.tensor(Str), torch.tensor(ytr), Xe=torch.tensor(Ftr), epochs=20)
                fitted = y
                run_model.cache = mdl
            mdl = run_model.cache
            mdl.eval()
            for k in te:
                v = P.VALID[k]
                if v.sum() < 20:
                    continue
                sk = P.SEQ[k][v]
                sk = np.clip(sk / (sk.std(axis=1, keepdims=True) + 1e-6), -6, 6)
                with torch.no_grad():
                    if name == "혼합CNN+특징":
                        pred[k, v] = mdl(torch.tensor(sk), torch.tensor(P.X[k][v])).numpy()
                    else:
                        pred[k, v] = mdl(torch.tensor(sk)).numpy()
    return pred, time.time() - t0


def ic_stats(pred):
    cc = []
    for k in range(NR):
        v = P.VALID[k] & np.isfinite(pred[k])
        if v.sum() < 30 or P.YEARS[k] < TEST_YEARS[0]:
            continue
        cc.append(np.corrcoef(pd.Series(pred[k, v]).rank(), pd.Series(P.FWD[k, v]).rank())[0, 1])
    cc = np.array(cc)
    return cc.mean(), cc.mean() / (cc.std() / np.sqrt(len(cc))), (cc > 0).mean(), len(cc)


if __name__ == "__main__":
    ST = f"{TEST_YEARS[0]}-01-01"
    b = Q.bench(start=ST)
    print(f"시험 기간 {ST}~2026, SPY CAGR {b['SPY 그냥 보유']['CAGR']:.1%} "
          f"샤프 {b['SPY 그냥 보유']['샤프']:.2f} 낙폭 {b['SPY 그냥 보유']['낙폭']:.0%}")
    print(f"동일가중 CAGR {b['지수 동일가중']['CAGR']:.1%} 샤프 {b['지수 동일가중']['샤프']:.2f}\n")
    rows = []
    preds = {}
    for name, every in [("Ridge", 1), ("부스팅", 1), ("랜덤포레스트", 2), ("신경망MLP", 1),
                        ("합성곱CNN", 2), ("순환신경망GRU", 3), ("혼합CNN+특징", 2)]:
        pr, el = run_model(name, every)
        preds[name] = pr
        m, t, pos, n = ic_stats(pr)
        r20 = Q.backtest(pr, n=20, cost=0.0025, start=ST)
        r50 = Q.backtest(pr, n=50, cost=0.0025, start=ST)
        rows.append(dict(모델=name, IC=m, t값=t, 양수월=pos,
                         상위20_CAGR=r20["CAGR"], 상위20_샤프=r20["샤프"], 상위20_낙폭=r20["낙폭"],
                         상위50_CAGR=r50["CAGR"], 회전율=r20["회전율"], 초=el))
        print(f"  {name:12s} IC {m:+.4f} (t {t:+.2f}) | 상위20 CAGR {r20['CAGR']:6.1%} "
              f"샤프 {r20['샤프']:.2f} | 상위50 {r50['CAGR']:6.1%} | {el:.0f}초", flush=True)
    ens = np.nanmean([preds[k] for k in preds], axis=0)
    m, t, pos, n = ic_stats(ens)
    r20 = Q.backtest(ens, n=20, cost=0.0025, start=ST)
    rows.append(dict(모델="7개 평균(앙상블)", IC=m, t값=t, 양수월=pos, 상위20_CAGR=r20["CAGR"],
                     상위20_샤프=r20["샤프"], 상위20_낙폭=r20["낙폭"], 상위50_CAGR=np.nan,
                     회전율=r20["회전율"], 초=0))
    print(f"  {'앙상블':12s} IC {m:+.4f} (t {t:+.2f}) | 상위20 CAGR {r20['CAGR']:6.1%} 샤프 {r20['샤프']:.2f}")
    pd.to_pickle({"rows": rows, "preds": preds, "ens": ens}, "qml.pkl")
    df = pd.DataFrame(rows)
    print("\n" + df.to_string(index=False, formatters={
        "IC": "{:+.4f}".format, "t값": "{:+.2f}".format, "양수월": "{:.0%}".format,
        "상위20_CAGR": "{:.1%}".format, "상위20_샤프": "{:.2f}".format, "상위20_낙폭": "{:.0%}".format,
        "상위50_CAGR": "{:.1%}".format, "회전율": "{:.0%}".format, "초": "{:.0f}".format}))
