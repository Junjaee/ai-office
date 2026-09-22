import warnings; warnings.filterwarnings("ignore")
import pandas as pd, yfinance as yf
T=["SPY","QQQ","IWM","EFA","EEM","TLT","IEF","SHY","AGG","GLD","DBC","VNQ","BIL","LQD","HYG",
   "XLK","XLE","XLF","XLV","XLI","XLP","XLU","XLB","XLY","XLC","XLRE","RSP","MTUM","USMV","QUAL","VLUE","SPLV"]
d=yf.download(T,start="1999-01-01",auto_adjust=True,progress=False,threads=True)["Close"]
d.index=d.index.tz_localize(None) if d.index.tz is not None else d.index
d=d[d["SPY"].notna()]
d.to_pickle("aa.pkl")
print("자산 수",d.shape[1])
for t in T:
    s=d[t].dropna()
    print(f"  {t:5s} {s.index[0].date()} ~ {s.index[-1].date()} ({len(s)}일)")
