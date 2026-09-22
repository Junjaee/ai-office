import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yfinance as yf
T=["SCHD","VOO","QQQ","QQQM","QLD","SPY","VEIPX","DVY","^VIX","^IRX","TQQQ"]
d=yf.download(T,start="1999-01-01",auto_adjust=True,progress=False,threads=False)["Close"]
d.index=d.index.tz_localize(None) if d.index.tz is not None else d.index
d=d[d["SPY"].notna()]; d.to_pickle("etf.pkl")
for t in T: s=d[t].dropna(); print(f"{t:6s} {s.index[0].date()} ~ {s.index[-1].date()}  {len(s)}일")
# 계산으로 만든 2배 지수가 진짜 QLD 와 얼마나 같은가
r=d["QQQ"].pct_change(); rf=(d["^IRX"].ffill()/100).fillna(0.02)
syn=(2*r-(0.0095+rf)/252)
ov=d["QLD"].dropna().index[1:]
real=d["QLD"].pct_change().loc[ov]; s2=syn.loc[ov]
yrs=(ov[-1]-ov[0]).days/365.25
print("겹치는 기간 연수익: 진짜 QLD",f"{(1+real).prod()**(1/yrs)-1:.1%}","/ 계산값",f"{(1+s2).prod()**(1/yrs)-1:.1%}","/ 일별 상관",round(real.corr(s2),4))
# 배당 대역(VEIPX)이 SCHD 와 얼마나 비슷한가
o2=d["SCHD"].dropna().index[1:]; a,b=d["SCHD"].pct_change().loc[o2],d["VEIPX"].pct_change().loc[o2]; y2=(o2[-1]-o2[0]).days/365.25
print("SCHD vs VEIPX: 연수익",f"{(1+a).prod()**(1/y2)-1:.1%}",f"{(1+b).prod()**(1/y2)-1:.1%}","/ 월 상관",round(d['SCHD'].resample('ME').last().pct_change().corr(d['VEIPX'].resample('ME').last().pct_change()),3))
for nm,a_,b_ in [("닷컴 2000-03~2002-10","2000-03-24","2002-10-09"),("금융위기 2007-10~2009-03","2007-10-09","2009-03-09"),("2022","2021-11-19","2022-12-28")]:
    seg=d.loc[a_:b_]; q=(1+syn.loc[a_:b_]).prod()-1
    print(nm,"| QQQ",f"{seg['QQQ'].iloc[-1]/seg['QQQ'].iloc[0]-1:.0%}","| 2배(계산)",f"{q:.0%}","| SPY",f"{seg['SPY'].iloc[-1]/seg['SPY'].iloc[0]-1:.0%}","| 배당 대역",f"{seg['VEIPX'].iloc[-1]/seg['VEIPX'].iloc[0]-1:.0%}")
