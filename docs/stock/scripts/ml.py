"""머신러닝으로 '지금 갈아타면 이득인가'를 맞힐 수 있는지 시험.

규칙: 학습은 과거만, 시험은 미래만. 목표가 앞으로 252일을 보므로 학습 끝과 시험 시작 사이에
252일을 비워(purge) 정답이 새지 않게 한다.
"""
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

import engine as E

H = 252  # 내다보는 기간(거래일)
P, VIX = E.P, E.VIX
IDX = P.index
nq, div, lev = P["NQ"], P["DIV"], P["L2"]


def features():
    f = pd.DataFrame(index=IDX)
    f["고점대비"] = nq / nq.rolling(252, min_periods=60).max() - 1
    f["VIX"] = VIX
    f["VIX변화20"] = VIX - VIX.rolling(20).mean()
    for m in (20, 50, 200):
        f[f"MA{m}이격"] = nq / nq.rolling(m).mean() - 1
    for m in (63, 126, 252):
        f[f"모멘텀{m}"] = nq / nq.shift(m) - 1
    f["변동성20"] = nq.pct_change().rolling(20).std() * np.sqrt(252)
    f["변동성60"] = nq.pct_change().rolling(60).std() * np.sqrt(252)
    r = pd.read_pickle("etf.pkl")["^IRX"].reindex(IDX).ffill()
    f["금리"] = r
    f["금리변화"] = r - r.rolling(120).mean()
    f["배당대비추세"] = (nq / nq.shift(126)) - (div / div.shift(126))
    return f


def build():
    f = features()
    fwd_lev = lev.shift(-H) / lev - 1
    fwd_div = div.shift(-H) / div - 1
    y = fwd_lev - fwd_div  # 갈아탔을 때의 초과 수익
    ok = f.notna().all(1) & y.notna()
    return f[ok], y[ok], IDX[ok]


def walk_forward(X, y, idx, n_splits=6):
    """확장 학습창 + 252일 공백. 각 구간에서 '학습 평균 예측'을 기준선으로 비교."""
    n = len(X)
    bounds = np.linspace(int(n * 0.35), n, n_splits + 1).astype(int)
    rows = []
    preds = pd.Series(np.nan, index=idx)
    for i in range(n_splits):
        te0, te1 = bounds[i], bounds[i + 1]
        tr1 = te0 - H  # 공백
        if tr1 < 250:
            continue
        Xtr, ytr = X.iloc[:tr1], y.iloc[:tr1]
        Xte, yte = X.iloc[te0:te1], y.iloc[te0:te1]
        m = HistGradientBoostingRegressor(max_depth=3, max_iter=250, learning_rate=0.05,
                                          min_samples_leaf=100, l2_regularization=1.0,
                                          random_state=0)
        m.fit(Xtr, ytr)
        p = m.predict(Xte)
        preds.iloc[te0:te1] = p
        base = ytr.mean()
        ss_res = ((yte - p) ** 2).sum()
        ss_bas = ((yte - base) ** 2).sum()
        rows.append({
            "시험구간": f"{idx[te0].date()}~{idx[te1-1].date()}",
            "일수": len(Xte),
            "실제평균": yte.mean(),
            "예측평균": p.mean(),
            "R2(학습평균 대비)": 1 - ss_res / ss_bas,
            "부호정확도": float(((p > 0) == (yte > 0)).mean()),
            "항상갈아탐정확도": float((yte > 0).mean()),
            "상관": float(np.corrcoef(p, yte)[0, 1]) if len(p) > 2 else np.nan,
        })
    return pd.DataFrame(rows), preds


if __name__ == "__main__":
    X, y, idx = build()
    print(f"표본: {len(X)}일 ({idx[0].date()}~{idx[-1].date()}), 특징 {X.shape[1]}개")
    print(f"목표가 {H}일을 겹쳐 보므로 실질적으로 독립인 표본은 약 {len(X)//H}개뿐이다.\n")
    tab, preds = walk_forward(X, y, idx)
    print(tab.round(3).to_string(index=False))
    v = tab["R2(학습평균 대비)"]
    print(f"\n전체 구간 R2 중앙값 {v.median():.3f} (0보다 크면 학습 평균보다 나음), "
          f"양수인 구간 {int((v>0).sum())}/{len(v)}")
    print(f"부호 정확도 평균 {tab['부호정확도'].mean():.3f} vs 무조건 갈아타기 {tab['항상갈아탐정확도'].mean():.3f}")
    preds.to_pickle("ml_preds.pkl")

    # 모델 신호를 실제 전략으로 돌려 본다
    cond = (preds > 0).reindex(IDX).fillna(False).values
    E._cache[("cust", 0, 0)] = E.next_true(cond)
    have = preds.dropna()
    st = str(have.index[0].date())
    a = E.simulate(st)
    b = E.simulate(st, entry="cust", thr=0, confirm=0, target=1.0)
    c = E.simulate(st, entry="dd", thr=0.2, target=1.0)
    print(f"\n모델 신호로 갈아타기({st}~): {b['배수']:.2f}배/{b['낙폭']:.0%} | "
          f"3등분만 {a['배수']:.2f}배/{a['낙폭']:.0%} | 고정규칙 -20% {c['배수']:.2f}배/{c['낙폭']:.0%}")
