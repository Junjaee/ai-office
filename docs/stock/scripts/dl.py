import warnings; warnings.filterwarnings("ignore")
import time, pandas as pd, yfinance as yf
syms=[s.replace(".","-") for s in pd.read_csv("sp500_wiki.csv")["Symbol"]]
extra=["SPY","^VIX","KRW=X","^GSPC"]
t=time.time()
df=yf.download(syms+extra,start="2005-01-01",interval="1d",auto_adjust=True,group_by="column",threads=8,progress=False)
miss=[s for s in syms+extra if df["Close"][s].notna().sum()==0]
if miss:
    time.sleep(3)
    d2=yf.download(miss,start="2005-01-01",interval="1d",auto_adjust=True,group_by="column",threads=False,progress=False)
    for f in ["Open","High","Low","Close","Volume"]:
        for s in miss:
            try: df[(f,s)]=d2[f][s] if len(miss)>1 else d2[f]
            except Exception as e: print("재시도 실패",s,e)
df.index=df.index.tz_localize(None) if df.index.tz is not None else df.index
df.to_pickle("px.pkl")
print(f"{time.time()-t:.0f}s, 모양 {df.shape}, 기간 {df.index[0].date()}~{df.index[-1].date()}, 빈 종목 {[s for s in syms if df['Close'][s].notna().sum()==0]}")
