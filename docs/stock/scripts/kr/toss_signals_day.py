"""토스 하루치(2026-09-29) 호가·체결 → 1분 단위 신호와 그 뒤 5·15·30분 수익률. 첫 시험(표본 하루)."""
import glob, os, sys
import numpy as np, pandas as pd

ROOT = os.path.join(os.path.expanduser("~"), "ai-office-data", "toss-record", "2026-09-29")
H = [5, 15, 30]

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
            df["code"] = code; df["run"] = os.path.basename(run)
            frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df["recv_ms"] = pd.to_numeric(df["recv_ms"], errors="coerce")
    df["t"] = pd.to_datetime(df["recv_ms"], unit="ms", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
    return df

book = load("orderbook"); trade = load("trade")
for c in [f"{s}{i}_{k}" for i in range(1, 11) for s in ("ask", "bid") for k in ("p", "v")] + ["ask_total", "bid_total"]:
    book[c] = pd.to_numeric(book[c], errors="coerce")
for c in ("price", "volume"):
    trade[c] = pd.to_numeric(trade[c], errors="coerce")
trade["ts"] = pd.to_datetime(trade["timestamp"], errors="coerce", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
trade["ts"] = trade["ts"].fillna(trade["t"])
book = book.sort_values("recv_ms"); trade = trade.sort_values("recv_ms")
book["mid"] = (book["ask1_p"] + book["bid1_p"]) / 2
book.loc[book["ask1_p"].isna() | (book["ask1_p"] <= 0), "mid"] = book["bid1_p"]   # 상한가
book.loc[book["bid1_p"].isna() | (book["bid1_p"] <= 0), "mid"] = book["ask1_p"]
print(f"호가 {len(book):,}행 · 체결 {len(trade):,}행 · 종목 {book.code.nunique()} · 시간 {book.t.min():%H:%M}~{book.t.max():%H:%M}")

# 체결 방향: 직전 호가와 대조(중간값 기준)
tr = pd.merge_asof(trade.sort_values("recv_ms"), book[["recv_ms", "code", "ask1_p", "bid1_p"]].sort_values("recv_ms"), on="recv_ms", by="code", direction="backward")
mid = (tr["ask1_p"] + tr["bid1_p"]) / 2
tr["side"] = np.where(tr["price"] >= tr["ask1_p"], "B", np.where(tr["price"] <= tr["bid1_p"], "S", np.where(tr["price"] >= mid, "B", "S")))
tr["amt"] = tr["price"] * tr["volume"]
tr["minute"] = tr["ts"].dt.floor("min")
flow = tr.pivot_table(index=["code", "minute"], columns="side", values="amt", aggfunc="sum").fillna(0).reset_index()
for s in ("B", "S"):
    if s not in flow: flow[s] = 0.0

# 1분 표: 마지막 호가 프레임 기준
book["minute"] = book["t"].dt.floor("min")
last = book.groupby(["code", "minute"]).last().reset_index()
m = last.merge(flow, on=["code", "minute"], how="left").fillna({"B": 0, "S": 0})
m = m.sort_values(["code", "minute"]).reset_index(drop=True)
g = m.groupby("code")
# 5분 창 합계(같은 run 안에서만)
m["run_key"] = m["code"] + "/" + m["run"]
gr = m.groupby("run_key")
m["B5"] = gr["B"].transform(lambda s: s.rolling(5, min_periods=1).sum()); m["S5"] = gr["S"].transform(lambda s: s.rolling(5, min_periods=1).sum())
m["flow5"] = np.log2((m["B5"] + 1) / (m["S5"] + 1)); m["amt5"] = m["B5"] + m["S5"]
m["ratio"] = m["bid_total"] / m["ask_total"].replace(0, np.nan)
# 가장 큰 벽(방향·금액), 5분 전 대비 벽 생김
def walls(df):
    amt_ask = pd.concat([df[f"ask{i}_p"] * df[f"ask{i}_v"] for i in range(1, 11)], axis=1)
    amt_bid = pd.concat([df[f"bid{i}_p"] * df[f"bid{i}_v"] for i in range(1, 11)], axis=1)
    return amt_ask.max(axis=1), amt_bid.max(axis=1)
m["wall_ask"], m["wall_bid"] = walls(m)
for side in ("ask", "bid"):
    for i in range(1, 6):
        v = m[f"{side}{i}_v"]; v0 = gr[f"{side}{i}_v"].shift(5); p = m[f"{side}{i}_p"]
        m[f"ev_{side}{i}"] = (v > 2 * v0.clip(lower=1)) & (p * v >= 1e8)
    m[f"event_{side}"] = m[[f"ev_{side}{i}" for i in range(1, 6)]].any(axis=1)
# 뒤 수익률(같은 run 안)
for h in H:
    m[f"ret{h}"] = gr["mid"].shift(-h) / m["mid"] - 1
m = m.replace([np.inf, -np.inf], np.nan)

def table(mask, name):
    rows = []
    for h in H:
        r = m.loc[mask, f"ret{h}"].dropna() * 100; base = m[f"ret{h}"].dropna() * 100
        if len(r) == 0: continue
        rows.append({"신호": name, "뒤": f"{h}분", "건수": len(r), "평균%": round(r.mean(), 3), "중앙%": round(r.median(), 3), "오를 확률": round((r > 0).mean(), 2), "전체 평균%": round(base.mean(), 3), "전체 오를 확률": round((base > 0).mean(), 2)})
    return rows

out = []
out += table(m["event_bid"], "매수벽 생김(2배·1억)")
out += table(m["event_ask"], "매도벽 생김(2배·1억)")
out += table((m["flow5"] >= 1) & (m["amt5"] >= 1e8), "5분 매수 체결 2배↑(1억↑)")
out += table((m["flow5"] <= -1) & (m["amt5"] >= 1e8), "5분 매도 체결 2배↑(1억↑)")
out += table(m["ratio"] >= 2, "잔량비 2 이상(매수 대기 2배)")
out += table(m["ratio"] <= 0.5, "잔량비 0.5 이하")
out += table((m["wall_bid"] / m["amt5"].clip(lower=1e7) >= 3) & (m["wall_bid"] >= 5e7), "매수벽 ≥ 5분 거래대금 3배")
out += table((m["wall_ask"] / m["amt5"].clip(lower=1e7) >= 3) & (m["wall_ask"] >= 5e7), "매도벽 ≥ 5분 거래대금 3배")
res = pd.DataFrame(out)
print(res.to_string(index=False))
print("\n종목-분 표본:", len(m), "| 5분 창 매수+매도 1억 이상인 분:", int((m.amt5 >= 1e8).sum()))
res.to_csv(os.path.join(os.path.dirname(__file__), "toss_day1_result.csv"), index=False, encoding="utf-8-sig")
