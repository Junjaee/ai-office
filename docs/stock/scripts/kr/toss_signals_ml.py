"""토스 하루치 → 여러 신호를 한꺼번에: (1) 매수벽 크기 × 체결강도 2차원 표, (2) 머신러닝(그래디언트 부스팅)으로 15분 뒤 수익률 예측, 시간순 검증(앞 60% 학습 → 뒤 40% 시험)."""
import glob, os
import numpy as np, pandas as pd

ROOT = os.path.join(os.path.expanduser("~"), "ai-office-data", "toss-record", "2026-09-29")
OUT = os.path.dirname(__file__)

def load(kind):
    frames = []
    for run in sorted(glob.glob(os.path.join(ROOT, "run_*"))):
        for p in glob.glob(os.path.join(run, f"{kind}_*.csv")) + glob.glob(os.path.join(run, f"{kind}_*.parquet")):
            code = os.path.basename(p).split("_")[1].split(".")[0]
            try:
                df = pd.read_parquet(p) if p.endswith(".parquet") else pd.read_csv(p, dtype=str)
            except Exception:
                continue
            if len(df) == 0: continue
            df["code"] = code; df["run"] = os.path.basename(run); frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["recv_ms"] = pd.to_numeric(df["recv_ms"], errors="coerce")
    df["t"] = pd.to_datetime(df["recv_ms"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
    return df

book = load("orderbook"); trade = load("trade")
lv = [f"{s}{i}_{k}" for i in range(1, 11) for s in ("ask", "bid") for k in ("p", "v")]
for c in lv + ["ask_total", "bid_total"]:
    book[c] = pd.to_numeric(book[c], errors="coerce")
for c in ("price", "volume"):
    trade[c] = pd.to_numeric(trade[c], errors="coerce")
trade["ts"] = pd.to_datetime(trade["timestamp"], errors="coerce", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None).fillna(trade["t"])
book = book.sort_values("recv_ms"); trade = trade.sort_values("recv_ms")
book["mid"] = (book["ask1_p"] + book["bid1_p"]) / 2
book.loc[book["ask1_p"].isna() | (book["ask1_p"] <= 0), "mid"] = book["bid1_p"]
book.loc[book["bid1_p"].isna() | (book["bid1_p"] <= 0), "mid"] = book["ask1_p"]

tr = pd.merge_asof(trade, book[["recv_ms", "code", "ask1_p", "bid1_p"]], on="recv_ms", by="code", direction="backward")
midq = (tr["ask1_p"] + tr["bid1_p"]) / 2
tr["side"] = np.where(tr["price"] >= tr["ask1_p"], "B", np.where(tr["price"] <= tr["bid1_p"], "S", np.where(tr["price"] >= midq, "B", "S")))
tr["amt"] = tr["price"] * tr["volume"]; tr["minute"] = tr["ts"].dt.floor("min")
flow = tr.pivot_table(index=["code", "minute"], columns="side", values="amt", aggfunc="sum").fillna(0).reset_index()
for s in ("B", "S"):
    if s not in flow: flow[s] = 0.0
ntr = tr.groupby(["code", "minute"]).size().rename("n_tr").reset_index()

book["minute"] = book["t"].dt.floor("min")
last = book.groupby(["code", "minute"]).last().reset_index()
frames_per_min = book.groupby(["code", "minute"]).size().rename("frames").reset_index()
m = last.merge(flow, on=["code", "minute"], how="left").merge(ntr, on=["code", "minute"], how="left").merge(frames_per_min, on=["code", "minute"], how="left")
m = m.fillna({"B": 0, "S": 0, "n_tr": 0}).sort_values(["code", "minute"]).reset_index(drop=True)
m["rk"] = m["code"] + "/" + m["run"]; gr = m.groupby("rk")

# ── 특징(전부 '그 분까지' 정보만) ──
for w in (5, 15):
    m[f"B{w}"] = gr["B"].transform(lambda s: s.rolling(w, min_periods=1).sum()); m[f"S{w}"] = gr["S"].transform(lambda s: s.rolling(w, min_periods=1).sum())
    m[f"flow{w}"] = np.log2((m[f"B{w}"] + 1) / (m[f"S{w}"] + 1)); m[f"amt{w}"] = m[f"B{w}"] + m[f"S{w}"]
m["strength5"] = m["B5"] / m["S5"].replace(0, np.nan) * 100
m["ratio"] = np.log2(m["bid_total"] / m["ask_total"].replace(0, np.nan))
m["spread"] = (m["ask1_p"] - m["bid1_p"]) / m["mid"]
amt_ask = pd.concat([m[f"ask{i}_p"] * m[f"ask{i}_v"] for i in range(1, 11)], axis=1); amt_bid = pd.concat([m[f"bid{i}_p"] * m[f"bid{i}_v"] for i in range(1, 11)], axis=1)
m["wall_ask"] = amt_ask.max(axis=1); m["wall_bid"] = amt_bid.max(axis=1)
m["wall_ask_lv"] = amt_ask.values.argmax(axis=1) + 1; m["wall_bid_lv"] = amt_bid.values.argmax(axis=1) + 1
base = m["amt5"].clip(lower=1e7)
m["wall_bid_rel"] = np.log2(1 + m["wall_bid"] / base); m["wall_ask_rel"] = np.log2(1 + m["wall_ask"] / base)
m["depth_bid_amt"] = amt_bid.sum(axis=1) / 1e8; m["depth_ask_amt"] = amt_ask.sum(axis=1) / 1e8
m["near_bid"] = (m["bid1_p"] * m["bid1_v"] + m["bid2_p"] * m["bid2_v"] + m["bid3_p"] * m["bid3_v"]) / 1e8
m["near_ask"] = (m["ask1_p"] * m["ask1_v"] + m["ask2_p"] * m["ask2_v"] + m["ask3_p"] * m["ask3_v"]) / 1e8
# 5분 전 대비 벽 변화(생김/사라짐)
for side in ("ask", "bid"):
    prev = gr[f"wall_{side}"].shift(5)
    m[f"wall_{side}_chg"] = np.log2((m[f"wall_{side}"] + 1e6) / (prev + 1e6))
    ev = None
    for i in range(1, 6):
        v = m[f"{side}{i}_v"]; v0 = gr[f"{side}{i}_v"].shift(5); p = m[f"{side}{i}_p"]
        e = ((v > 2 * v0.clip(lower=1)) & (p * v >= 1e8)) * (p * v)
        ev = e if ev is None else np.maximum(ev, e)
    m[f"event_{side}_amt"] = ev / 1e8
# 가격 흐름
for w in (1, 5, 15):
    m[f"mom{w}"] = m["mid"] / gr["mid"].shift(w) - 1
m["vol15"] = gr["mom1"].transform(lambda s: s.rolling(15, min_periods=3).std())
m["hour"] = m["minute"].dt.hour + m["minute"].dt.minute / 60
m["log_amt5"] = np.log10(m["amt5"] + 1)
# 목표
for h in (5, 15, 30):
    m[f"ret{h}"] = gr["mid"].shift(-h) / m["mid"] - 1
m = m.replace([np.inf, -np.inf], np.nan)

FEATS = ["flow5", "flow15", "strength5", "log_amt5", "ratio", "spread", "wall_bid_rel", "wall_ask_rel", "wall_bid_lv", "wall_ask_lv", "depth_bid_amt", "depth_ask_amt",
         "near_bid", "near_ask", "wall_bid_chg", "wall_ask_chg", "event_bid_amt", "event_ask_amt", "mom1", "mom5", "mom15", "vol15", "n_tr", "frames", "hour"]
TARGET = "ret15"
d = m.dropna(subset=[TARGET, "mid"]).copy()
d["y"] = d[TARGET] * 100
print(f"표본(종목-분) {len(d):,} · 종목 {d.code.nunique()} · 특징 {len(FEATS)}")

# ── (1) 2차원 표: 매수벽 크기 × 체결강도 → 15분 뒤 평균 수익률 ──
d["벽구간"] = pd.cut(d["wall_bid_rel"], [-0.01, 0.5, 1, 2, 10], labels=["작음(<1.4배)", "보통", "큼(≥2배)", "아주 큼(≥4배)"])
d["강도구간"] = pd.cut(d["strength5"].fillna(100), [-1, 50, 100, 200, 1e9], labels=["매도 우위(<50)", "약함(50~100)", "매수 우위(100~200)", "강함(≥200)"])
pv = d[d.amt5 >= 3e7].pivot_table(index="벽구간", columns="강도구간", values="y", aggfunc=["mean", "count"], observed=True)
print("\n[매수벽 크기(÷5분 거래대금) × 5분 체결강도 → 15분 뒤 평균 %, 건수] (5분 체결 0.3억 이상)")
print(pv.round(3).to_string())
d["잔량구간"] = pd.cut(d["ratio"], [-10, -1, 0, 1, 10], labels=["매도 대기 2배↑", "매도 쪽", "매수 쪽", "매수 대기 2배↑"])
pv2 = d.pivot_table(index="잔량구간", columns="강도구간", values="y", aggfunc=["mean", "count"], observed=True)
print("\n[잔량비 × 체결강도 → 15분 뒤 평균 %, 건수]"); print(pv2.round(3).to_string())

# ── (2) 머신러닝: 시간순 앞 60% 학습, 뒤 40% 시험 ──
from sklearn.ensemble import HistGradientBoostingRegressor, HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score
from scipy.stats import spearmanr
d = d.sort_values("minute")
cut = d["minute"].quantile(0.6)
trn, tst = d[d.minute <= cut], d[d.minute > cut]
print(f"\n학습 {len(trn):,}(~{cut:%H:%M}) / 시험 {len(tst):,}({tst.minute.min():%H:%M}~)")
reg = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=300, min_samples_leaf=200, l2_regularization=1.0, random_state=0)
reg.fit(trn[FEATS], trn["y"])
pred = reg.predict(tst[FEATS])
ic, _ = spearmanr(pred, tst["y"])
tst = tst.assign(pred=pred)
tst["십분위"] = pd.qcut(tst["pred"], 10, labels=False, duplicates="drop")
dec = tst.groupby("십분위")["y"].agg(["mean", "count"]).round(3)
print(f"\n[예측 순위 vs 실제 15분 수익률] 순위상관(IC) = {ic:.3f}")
print(dec.to_string())
top, bot = tst[tst.십분위 == tst.십분위.max()]["y"], tst[tst.십분위 == 0]["y"]
print(f"상위10% 평균 {top.mean():.3f}% (오를 확률 {(top > 0).mean():.2f}) vs 하위10% {bot.mean():.3f}% (오를 확률 {(bot > 0).mean():.2f}) vs 전체 {tst.y.mean():.3f}%")
clf = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=300, min_samples_leaf=200, l2_regularization=1.0, random_state=0)
clf.fit(trn[FEATS], (trn["y"] > 0.3).astype(int))
p = clf.predict_proba(tst[FEATS])[:, 1]
print(f"'15분 안에 +0.3% 이상' 분류 AUC = {roc_auc_score((tst['y'] > 0.3).astype(int), p):.3f} (0.5 = 동전던지기), 기저율 {(tst['y'] > 0.3).mean():.2f}")
# 특징 중요도(순열)
from sklearn.inspection import permutation_importance
pi = permutation_importance(reg, tst[FEATS], tst["y"], n_repeats=5, random_state=0, scoring="neg_mean_squared_error")
imp = pd.Series(pi.importances_mean, index=FEATS).sort_values(ascending=False)
print("\n[특징 중요도(시험 구간, 순열)] 상위 12"); print(imp.head(12).round(5).to_string())
# 가짜 목표(뒤섞기) 대조
rng = np.random.default_rng(0); ys = trn["y"].sample(frac=1, random_state=0).to_numpy()
reg2 = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=300, min_samples_leaf=200, l2_regularization=1.0, random_state=0).fit(trn[FEATS], ys)
ic2, _ = spearmanr(reg2.predict(tst[FEATS]), tst["y"])
print(f"\n[대조] 정답을 뒤섞어 학습한 모델의 IC = {ic2:.3f}")
d.to_parquet(os.path.join(OUT, "toss_features_2026-09-29.parquet"))
