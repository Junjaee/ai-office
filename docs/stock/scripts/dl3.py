import warnings; warnings.filterwarnings("ignore")
import time, numpy as np, pandas as pd, yfinance as yf
hist=pd.read_pickle("members.pkl")
ever=sorted(set().union(*hist[hist.index>="2005-01-01"]))
print("2005년 이후 한 번이라도 S&P500 이던 티커:",len(ever))
have=set(pd.read_pickle("px.pkl")["Close"].columns)
need=[t for t in ever if t not in have]
print("이미 있는 것:",len(ever)-len(need),"/ 새로 받아야 할 것:",len(need))
t0=time.time(); got={}
for i in range(0,len(need),60):
    ch=need[i:i+60]
    try:
        d=yf.download(ch,start="2004-06-01",auto_adjust=True,progress=False,threads=True,group_by="column")
        for c in ["Open","Close","Volume"]:
            if c not in d: continue
        for s in ch:
            try:
                cl=d["Close"][s].dropna()
                if len(cl)>60: got[s]=True
            except Exception: pass
    except Exception as e: print("묶음 실패",i,str(e)[:60])
    if i%300==0: print(f"  {i}/{len(need)} 누적성공 {len(got)} {time.time()-t0:.0f}초",flush=True)
print(f"추가로 받아진 종목: {len(got)}/{len(need)} ({time.time()-t0:.0f}초)")
pd.to_pickle(sorted(got),"extra_ok.pkl")
