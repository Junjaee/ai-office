import warnings; warnings.filterwarnings("ignore")
import io, sys, numpy as np, pandas as pd, requests
px=pd.read_pickle("px.pkl"); px=px[px["Close"]["SPY"].notna()]
syms=[s.replace(".","-") for s in pd.read_csv("sp500_wiki.csv")["Symbol"]]
O,H,L,C,V=(px[f] for f in ["Open","High","Low","Close","Volume"])
idx=C.index
# ── 과거 시점의 구성 종목(있으면) ──
try:
    hist=pd.read_pickle("members.pkl")
except Exception:
    url="https://raw.githubusercontent.com/fja05680/sp500/master/S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv"
    r=requests.get(url,timeout=60); h=pd.read_csv(io.StringIO(r.text)); h["date"]=pd.to_datetime(h["date"])
    hist=h.set_index("date")["tickers"].apply(lambda s:set(x.replace(".","-") for x in s.split(","))); hist.to_pickle("members.pkl")
print("구성 이력:",hist.index[0].date(),"~",hist.index[-1].date(),len(hist),"행", file=sys.stderr)
hs=hist.reindex(idx,method="ffill")
ever=set().union(*hist[hist.index>="2006-01-01"]); print("2006년 이후 한 번이라도 구성 종목이었던 티커:",len(ever),"/ 그중 지금 시세가 있는 것:",len(ever&set(syms)), file=sys.stderr)
member=pd.DataFrame({s:[s in m if isinstance(m,set) else False for m in hs] for s in syms},index=idx)
last_hist=hist.index[-1]; member.loc[idx>last_hist,:]=True   # 이력 파일 이후는 현재 목록
allcur=pd.DataFrame(True,index=idx,columns=syms)

def sim(O,C,entry,exit_,score,member,max_pos,cost=0.003,maxhold=None,start="2006-01-03"):
    cols=list(C.columns); Oa,Ca=O[cols].values,C[cols].ffill().values
    en,ex,sc,mb=entry[cols].values,exit_[cols].values,score[cols].values,member[cols].values
    t0=idx.get_indexer([pd.Timestamp(start)],method="bfill")[0]
    cash=1.0; pos={}; eq=np.full(len(idx),np.nan); eq[t0-1]=1.0; trades=[]
    for t in range(t0,len(idx)):
        for j in list(pos):
            sh,bp,bt_=pos[j]
            if (ex[t-1,j] or (maxhold and t-bt_>=maxhold)) and not np.isnan(Oa[t,j]):
                sp=Oa[t,j]*(1-cost); cash+=sh*sp; trades.append((idx[bt_],idx[t],cols[j],sp/bp-1,t-bt_)); del pos[j]
        free=max_pos-len(pos)
        if free>0:
            cand=[j for j in np.where(en[t-1]&mb[t-1])[0] if j not in pos and not np.isnan(Oa[t,j]) and not np.isnan(sc[t-1,j])]
            cand.sort(key=lambda j:-sc[t-1,j])
            for j in cand[:free]:
                amt=min(eq[t-1]/max_pos,cash)
                if amt<=0: break
                bp=Oa[t,j]*(1+cost); pos[j]=(amt/bp,bp,t); cash-=amt
        eq[t]=cash+sum(sh*Ca[t,j] for j,(sh,_,_) in pos.items())
    return pd.Series(eq,index=idx).dropna(), pd.DataFrame(trades,columns=["in","out","sym","ret","days"])

def stats(eq,tr=None,a=None,b=None):
    e=eq[(eq.index>=(a or eq.index[0]))&(eq.index<=(b or eq.index[-1]))]; r=e.pct_change().dropna(); y=(e.index[-1]-e.index[0]).days/365.25
    out={"연수익":f"{(e.iloc[-1]/e.iloc[0])**(1/y)-1:.1%}","변동성":f"{r.std()*252**.5:.1%}","최대낙폭":f"{(e/e.cummax()-1).min():.1%}","수익/변동":f"{r.mean()*252/(r.std()*252**.5):.2f}"}
    if tr is not None and len(tr):
        x=tr[(tr["in"]>=e.index[0])&(tr["in"]<=e.index[-1])]
        out.update({"거래/년":f"{len(x)/y:.0f}","승률":f"{(x.ret>0).mean():.0%}","평균손익":f"{x.ret.mean():.2%}","평균보유일":f"{x.days.mean():.0f}"})
    return out

ma=lambda n:C.rolling(n).mean()
spy=C["SPY"]; mkt_up=(spy>spy.rolling(200).mean())
mk=pd.DataFrame(np.repeat(mkt_up.values[:,None],len(syms),1),index=idx,columns=syms)
Cs,Os=C[syms],O[syms]
def rsi(s,n):
    d=s.diff(); up=d.clip(lower=0).ewm(alpha=1/n,adjust=False).mean(); dn=(-d.clip(upper=0)).ewm(alpha=1/n,adjust=False).mean(); return 100-100/(1+up/dn)
res={}
# R0 지수 그냥 보유
res["R0 지수 ETF 그냥 보유"]=(spy/spy[idx>="2006-01-03"].iloc[0],None)
# R1 지수 200일선
one=pd.DataFrame({"SPY":True},index=idx)
res["R1 지수 ETF, 200일선 위에서만"]=sim(O[["SPY"]],C[["SPY"]],mkt_up.to_frame("SPY"),(~mkt_up).to_frame("SPY"),pd.DataFrame({"SPY":1.0},index=idx),one,1)
# R2 모멘텀(12-1개월) 월 1회 상위 10
mom=Cs.shift(21)/Cs.shift(252)-1
me=pd.Series(idx,index=idx).groupby([idx.year,idx.month]).transform("max")==pd.Series(idx,index=idx); me=me.values
def mom_rule(member,filt):
    rk=mom.where(member).rank(axis=1,ascending=False); top=(rk<=10)
    if filt: top=top&mk
    en=top.copy(); en.loc[~me,:]=False; ex=(~top).copy(); ex.loc[~me,:]=False
    return sim(Os,Cs,en,ex,mom,member,10)
res["R2 모멘텀 상위10 (그때의 구성 종목)"]=mom_rule(member,False)
res["R2b 모멘텀 상위10 + 시장 필터"]=mom_rule(member,True)
res["R2x 모멘텀 상위10 (지금의 503개로 — 편향 확인용)"]=mom_rule(allcur,False)
# R3 눌림목: 200일선 위 & RSI(2)<10 → 5일선 위로 오면 청산
r2=Cs.apply(lambda s:rsi(s,2)); m200,m5=Cs.rolling(200).mean(),Cs.rolling(5).mean()
en=(r2<10)&(Cs>m200); ex=(Cs>m5)
res["R3 눌림목 RSI(2)<10 (최대 10종목)"]=sim(Os,Cs,en,ex,-r2,member,10,maxhold=10)
res["R3b 눌림목 + 시장 필터"]=sim(Os,Cs,en&mk,ex,-r2,member,10,maxhold=10)
# R4 신고가 돌파: 252일 종가 신고가 → 50일선 아래로 가면 청산
hi=Cs.rolling(252).max(); newhi=(Cs>=hi)&(Cs.shift(1)<hi.shift(1)); m50=Cs.rolling(50).mean()
volr=V[syms]/V[syms].rolling(50).mean()
res["R4 52주 신고가 돌파 (최대 10종목)"]=sim(Os,Cs,newhi,(Cs<m50),volr,member,10)
res["R4b 신고가 돌파 + 시장 필터"]=sim(Os,Cs,newhi&mk,(Cs<m50),volr,member,10)
pd.to_pickle(res,"res.pkl")
for nm,(eq,tr) in res.items():
    print("\n■",nm)
    for lab,a,b in [("전체 2006~2026",None,None),("앞 절반 2006~2015",None,"2015-12-31"),("뒤 절반 2016~2026","2016-01-01",None)]:
        print("  ",lab,stats(eq,tr,a and pd.Timestamp(a),b and pd.Timestamp(b)))
