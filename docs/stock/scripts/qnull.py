"""대조군: 무작위로 20종목 고르기 / 저가주 특징을 뺀 모델 / 우연 시험."""
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

import qengine as Q
import qpanel as P

ST = "2011-01-01"
b = Q.bench(start=ST)
sp = b["SPY 그냥 보유"]
print(f"기준 SPY {sp['CAGR']:.1%} 샤프 {sp['샤프']:.2f} 낙폭 {sp['낙폭']:.0%} | "
      f"동일가중 {b['지수 동일가중']['CAGR']:.1%} 샤프 {b['지수 동일가중']['샤프']:.2f}")

print("\n== 1. 무작위로 고른 20종목 (100회) ==")
rng = np.random.default_rng(1)
res = []
for s in range(100):
    sc = rng.standard_normal((P.NR, P.NT))
    r = Q.backtest(sc, n=20, cost=0.0025, start=ST)
    res.append((r["CAGR"], r["샤프"], r["낙폭"]))
a = np.array(res)
for lab, col in [("CAGR", 0), ("샤프", 1), ("낙폭", 2)]:
    v = a[:, col]
    f = "{:.1%}" if lab != "샤프" else "{:.2f}"
    print(f"  무작위 20종목 {lab}: 중앙값 {f.format(np.median(v))}, "
          f"10~90% 구간 {f.format(np.quantile(v,.1))}~{f.format(np.quantile(v,.9))}, "
          f"최고 {f.format(v.max())}")

print("\n== 2. 모델 성적을 무작위와 견주면 ==")
try:
    ml = pd.read_pickle("qml.pkl")
    for row in ml["rows"]:
        c, s_ = row["상위20_CAGR"], row["상위20_샤프"]
        pc = (a[:, 0] >= c).mean()
        ps = (a[:, 1] >= s_).mean()
        print(f"  {row['모델']:14s} CAGR {c:6.1%} → 무작위 100회 중 이만큼 좋은 경우 {pc:4.0%} | "
              f"샤프 {s_:.2f} → {ps:4.0%}")
except FileNotFoundError:
    print("  (머신러닝 결과 대기 중)")

print("\n== 3. '저가주' 특징을 빼면 모델 성적이 어떻게 되나 ==")
from sklearn.ensemble import RandomForestRegressor

keep = [i for i, f in enumerate(P.FEATS) if f != "가격"]
TEST_YEARS = list(range(2011, 2027))
for tag, cols in [("전체 특징 19개", list(range(len(P.FEATS)))), ("저가주 빼고 18개", keep)]:
    pred = np.full((P.NR, P.NT), np.nan, dtype=np.float32)
    fitted = None
    mdl = None
    for y in TEST_YEARS:
        te = np.where(P.YEARS == y)[0]
        tr = np.arange(0, te[0] - 2)
        if len(tr) < 48:
            continue
        if fitted is None or y - fitted >= 2:
            m = P.VALID[tr]
            Xtr = P.X[tr][m][:, cols]
            ytr = P.Y[tr][m]
            mdl = RandomForestRegressor(n_estimators=150, max_depth=8, min_samples_leaf=100,
                                        n_jobs=12, random_state=0).fit(Xtr, ytr)
            fitted = y
        for k in te:
            v = P.VALID[k]
            if v.sum() >= 20:
                pred[k, v] = mdl.predict(P.X[k][v][:, cols])
    r = Q.backtest(pred, n=20, cost=0.0025, start=ST)
    cc = []
    for k in range(P.NR):
        v = P.VALID[k] & np.isfinite(pred[k])
        if v.sum() > 30 and P.YEARS[k] >= 2011:
            cc.append(np.corrcoef(pd.Series(pred[k, v]).rank(), pd.Series(P.FWD[k, v]).rank())[0, 1])
    cc = np.array(cc)
    print(f"  랜덤포레스트 · {tag:14s}: CAGR {r['CAGR']:6.1%} 샤프 {r['샤프']:.2f} "
          f"낙폭 {r['낙폭']:.0%} | IC {cc.mean():+.4f} (t {cc.mean()/(cc.std()/np.sqrt(len(cc))):+.2f})")

print("\n== 4. 2021년 이후만 (시세 보유율 94% 이상) ==")
b2 = Q.bench(start="2021-01-01")
print(f"  SPY {b2['SPY 그냥 보유']['CAGR']:.1%} 샤프 {b2['SPY 그냥 보유']['샤프']:.2f}")
try:
    for row, nm in [(ml["preds"][k], k) for k in ml["preds"]]:
        r = Q.backtest(row, n=20, cost=0.0025, start="2021-01-01")
        print(f"  {nm:14s} CAGR {r['CAGR']:6.1%} 샤프 {r['샤프']:.2f} 낙폭 {r['낙폭']:.0%}")
except Exception:
    pass
