import warnings; warnings.filterwarnings("ignore")
import time, numpy as np, pandas as pd, yfinance as yf
extra=pd.read_pickle("extra_ok.pkl"); print("추가 대상",len(extra))
frames=[]
t0=time.time()
for i in range(0,len(extra),60):
    ch=extra[i:i+60]
    d=yf.download(ch,start="2004-06-01",auto_adjust=True,progress=False,threads=True,group_by="column")
    frames.append(d[["Open","Close","Volume"]])
    print(f"  {i+len(ch)}/{len(extra)} {time.time()-t0:.0f}초",flush=True)
add=pd.concat(frames,axis=1)
old=pd.read_pickle("px.pkl")[["Open","Close","Volume"]]
add.index=add.index.tz_localize(None) if add.index.tz is not None else add.index
full=pd.concat([old,add],axis=1).sort_index()
full=full.loc[:,~full.columns.duplicated()]
full.to_pickle("px_full.pkl")
cl=full["Close"]
print("전체 종목수",cl.shape[1],"기간",cl.index[0].date(),"~",cl.index[-1].date())
print("데이터가 끝난(상장폐지·피인수) 종목:",int((cl.ffill().isna().sum()==0).sum()),"중 마지막날 값이 있는 종목",int(cl.iloc[-1].notna().sum()))
