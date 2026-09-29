import os
import numpy as np, pandas as pd
OUT = os.path.dirname(__file__)
d = pd.read_parquet(os.path.join(OUT, "toss_features2_2026-09-29.parquet"))
x = d.dropna(subset=["ret15", "avg_amt5"]).copy()
x["배수구간"] = pd.cut(x["amt_ratio"], [0, 1, 2, 4, 8, 1e9], labels=["평소 이하", "1~2배", "2~4배", "4~8배", "8배↑"])
x["자리"] = np.select([x.above_high20 == 1, x.above_prev_high == 1, x.at_day_high == 1], ["20일 신고가", "전일 고가 돌파", "당일 고가"], "그 외")
for target, ml, name in (("ret15", 0, "15분 뒤"), ("ret_close", 20, "장 끝까지(20분 이상 남은 분만)")):
    xx = x[x.min_left >= ml]
    mean_t = xx.pivot_table(index="배수구간", columns="자리", values=target, aggfunc="mean", observed=True) * 100
    cnt_t = xx.pivot_table(index="배수구간", columns="자리", values=target, aggfunc="count", observed=True)
    print(f"\n[거래대금 배수 × 자리 → {name} 평균 %]"); print(mean_t.round(3).to_string()); print("건수"); print(cnt_t.to_string())
xx = x[x.min_left >= 20].copy()
xx["시간"] = pd.cut(xx["hour"], [9, 10, 11, 13, 14.5, 16], labels=["9시대", "10시대", "11~13시", "13~14:30", "14:30 이후"])
xx["흐름"] = pd.cut(xx["mom15"] * 100, [-99, -1, 0, 1, 99], labels=["−1%↓", "약보합", "약강세", "+1%↑"])
print("\n[시간대 × 15분 흐름 → 장 끝까지 평균 % (20분 이상 남은 분만)]")
print((xx.pivot_table(index="시간", columns="흐름", values="ret_close", aggfunc="mean", observed=True) * 100).round(3).to_string())
xx["등락"] = pd.cut(xx["chg"] * 100, [-99, -3, 0, 3, 10, 99], labels=["−3%↓", "−3~0", "0~3", "3~10", "10%↑"])
xx["신고가거리"] = pd.cut(xx["dist_high20"] * 100, [-99, -20, -10, -3, 0, 99], labels=["−20%↓", "−20~−10", "−10~−3", "−3~0", "돌파"])
print("\n[당일 등락률 × 20일 신고가와의 거리 → 장 끝까지 평균 %]")
print((xx.pivot_table(index="등락", columns="신고가거리", values="ret_close", aggfunc="mean", observed=True) * 100).round(3).to_string())
print("건수"); print(xx.pivot_table(index="등락", columns="신고가거리", values="ret_close", aggfunc="count", observed=True).to_string())
print("\n[매수 잔량 총액(억) 구간 → 장 끝까지 평균 %]")
xx["매수잔량"] = pd.cut(xx["depth_bid_amt"], [0, 1, 3, 10, 30, 1e9], labels=["<1억", "1~3억", "3~10억", "10~30억", "30억↑"])
print((xx.groupby("매수잔량", observed=True)["ret_close"].agg(["mean", "count"]).assign(mean=lambda t: t["mean"] * 100)).round(3).to_string())
