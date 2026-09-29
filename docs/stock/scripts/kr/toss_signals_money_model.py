"""새 기준(돈 몰림: 거래대금 배수·자리·흐름·시간) vs 기존 호가 기준 — 오늘 자료로 모델 비교. 목표: 15분 뒤, 장 끝(15:29)까지."""
import os, sys
import numpy as np, pandas as pd

sys.path.insert(0, r"G:\내 드라이브\dev\자동화\automations\toss_record"); sys.path.insert(0, r"G:\내 드라이브\dev\자동화\automations\kis_record")
OUT = os.path.dirname(__file__)
d = pd.read_parquet(os.path.join(OUT, "toss_features_2026-09-29.parquet"))
codes = sorted(d.code.unique())

# 일봉 기준값(토스): 캐시
ref_path = os.path.join(OUT, "daily_ref_2026-09-29.json")
import json
if os.path.exists(ref_path):
    ref = json.load(open(ref_path, encoding="utf-8"))
else:
    import toss_rest as tr
    from daily_ref import daily_refs
    tr.load_secrets(r"G:\내 드라이브\dev\자동화\ai-home\02_주식신호\config.yaml")
    ses = tr.Session(log=lambda m: None)
    ref = daily_refs(ses, codes, log=print)
    json.dump(ref, open(ref_path, "w", encoding="utf-8"))
print("기준값 종목", len(ref))
r = pd.DataFrame.from_dict(ref, orient="index"); r.index.name = "code"; r = r.reset_index()
d = d.merge(r, on="code", how="left")
d = d.sort_values(["code", "minute"]).reset_index(drop=True)
g = d.groupby(["code", "run"])

# ── 새 기준 특징 ──
d["amt_ratio"] = d["amt5"] / d["avg_amt5"].clip(lower=1e6)                      # 5분 거래대금 ÷ 평소 5분
d["log_amt_ratio"] = np.log2(d["amt_ratio"].clip(lower=0.01))
d["day_high"] = g["mid"].cummax()
d["at_day_high"] = (d["mid"] >= d["day_high"] * 0.999).astype(int)
d["above_prev_high"] = (d["mid"] > d["prev_high"]).astype(int)
d["above_high20"] = (d["mid"] > d["high20"]).astype(int)
d["chg"] = d["mid"] / d["prev_close"] - 1
d["late_strong"] = ((d["hour"] >= 14.5) & (d["mom15"] > 0)).astype(int)
d["dist_high20"] = d["mid"] / d["high20"] - 1
# 장 끝까지 수익률(같은 run 안 마지막 mid)
d["mid_last"] = g["mid"].transform("last"); d["ret_close"] = d["mid_last"] / d["mid"] - 1
d["min_left"] = (g["minute"].transform("max") - d["minute"]).dt.total_seconds() / 60

MONEY = ["log_amt_ratio", "at_day_high", "above_prev_high", "above_high20", "dist_high20", "chg", "mom5", "mom15", "late_strong", "hour", "vol15"]
BOOK = ["flow5", "flow15", "strength5", "ratio", "spread", "wall_bid_rel", "wall_ask_rel", "wall_bid_chg", "wall_ask_chg", "event_bid_amt", "event_ask_amt", "depth_bid_amt", "depth_ask_amt", "near_bid", "near_ask"]
ALL = MONEY + BOOK + ["log_amt5", "frames", "n_tr"]

from sklearn.ensemble import HistGradientBoostingRegressor
from scipy.stats import spearmanr

def run(feats, target, name, min_left=0):
    x = d.dropna(subset=[target, "avg_amt5"]).copy()
    if min_left: x = x[x.min_left >= min_left]
    x["y"] = x[target] * 100
    x = x.sort_values("minute"); cut = x["minute"].quantile(0.6)
    trn, tst = x[x.minute <= cut], x[x.minute > cut]
    m = HistGradientBoostingRegressor(max_depth=4, learning_rate=0.05, max_iter=300, min_samples_leaf=200, l2_regularization=1.0, random_state=0).fit(trn[feats], trn["y"])
    p = m.predict(tst[feats]); ic = spearmanr(p, tst["y"])[0]
    tst = tst.assign(pred=p); tst["dec"] = pd.qcut(tst["pred"], 10, labels=False, duplicates="drop")
    top = tst[tst.dec == tst.dec.max()]["y"]; bot = tst[tst.dec == 0]["y"]
    print(f"{name:34s} | {target:9s} | 시험 {len(tst):5d} | IC {ic:+.3f} | 상위10% {top.mean():+.3f}%(오를 확률 {(top>0).mean():.2f}) | 하위10% {bot.mean():+.3f}% | 전체 {tst.y.mean():+.3f}%")
    return m, tst

print("\n[모델 비교: 앞 60% 학습 → 뒤 40% 시험]")
for target, ml in (("ret15", 0), ("ret_close", 20)):
    run(MONEY, target, "돈 몰림(거래대금·자리·흐름·시간)", ml)
    run(BOOK, target, "호가(체결 방향·벽·잔량)", ml)
    m_all, tst = run(ALL, target, "둘 다", ml)

# ── 단순 규칙 표: 거래대금 배수 × 자리 → 15분·장 끝 ──
x = d.dropna(subset=["ret15", "avg_amt5"]).copy()
x["배수구간"] = pd.cut(x["amt_ratio"], [0, 1, 2, 4, 8, 1e9], labels=["평소 이하", "1~2배", "2~4배", "4~8배", "8배↑"])
x["자리"] = np.select([x.above_high20 == 1, x.above_prev_high == 1, x.at_day_high == 1], ["20일 신고가", "전일 고가 돌파", "당일 고가"], "그 외")
for target in ("ret15", "ret_close"):
    pv = x.pivot_table(index="배수구간", columns="자리", values=target, aggfunc=["mean", "count"], observed=True)
    pv.loc[:, "mean"] = pv["mean"] * 100
    print(f"\n[거래대금 배수 × 자리 → {'15분 뒤' if target=='ret15' else '장 끝까지'} 평균 %, 건수]"); print(pv.round(3).to_string())
# 시간대 × 15분 흐름
x["시간"] = pd.cut(x["hour"], [9, 10, 11, 13, 14.5, 16], labels=["9시대", "10시대", "11~13시", "13~14:30", "14:30 이후"])
x["흐름"] = pd.cut(x["mom15"] * 100, [-99, -1, 0, 1, 99], labels=["−1%↓", "약보합", "약강세", "+1%↑"])
pv = x.pivot_table(index="시간", columns="흐름", values="ret_close", aggfunc="mean", observed=True) * 100
print("\n[시간대 × 15분 흐름 → 장 끝까지 평균 %]"); print(pv.round(3).to_string())

from sklearn.inspection import permutation_importance
pi = permutation_importance(m_all, tst[ALL], tst["y"], n_repeats=5, random_state=0, scoring="neg_mean_squared_error")
print("\n[둘 다 모델(장 끝 목표) 특징 중요도 상위 10]"); print(pd.Series(pi.importances_mean, index=ALL).sort_values(ascending=False).head(10).round(5).to_string())
d.to_parquet(os.path.join(OUT, "toss_features2_2026-09-29.parquet"))
