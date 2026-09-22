import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, itertools
pd.set_option("display.width",250)
d=pd.read_pickle("etf.pkl")
def splice(new,old):
    r=d[new].pct_change().where(d[new].notna()&d[new].shift().notna(), d[old].pct_change()); return (1+r.fillna(0)).cumprod()
rf=(d["^IRX"].ffill()/100).fillna(0.02)
d["SYN2"]=(1+(2*d["QQQ"].pct_change()-(0.0095+rf)/252).fillna(0)).cumprod()
d["SYN3"]=(1+(3*d["QQQ"].pct_change()-(0.0086+2*rf)/252).fillna(0)).cumprod()
P=pd.DataFrame({"DIV":splice("SCHD","VEIPX"),"SP":d["SPY"],"NQ":d["QQQ"],"L2":splice("QLD","SYN2"),"L3":splice("TQQQ","SYN3")})[d["QQQ"].notna()]
VIX=d["^VIX"].reindex(P.index).ffill(); HI=P["NQ"].rolling(252,min_periods=1).max()
COST,TAX=0.003,0.22
# 자산: 0 DIV, 1 SP, 2 NQ, 3 목적지(레버리지 or NQ)
def run(start,entry=None,x=0.2,exit_="p100",dest="L2",src=0,cap=None,stop=None,newmoney=False,lump=True,tax=True,static=None):
    cols=["DIV","SP","NQ",dest]; m=P.index>=start; idx=P.index[m]; A=P[cols].values[m]; nq=A[:,2]; dd=nq/HI.values[m]-1; vix=VIX.values[m]
    sh=np.zeros(4); cb=np.zeros(4); units=0.0; unit=1.0; contrib=0.0; flows=[]; uv=[]; realized=0.0; taxpaid=0.0
    inlev=False; armed=True; pend=None; nsw=0; nstop=0; month=None; moved=0.0; ev=[]
    def sell(i,f,t):
        nonlocal realized
        v=sh[i]*A[t,i]*f; realized+=v-cb[i]*f; cb[i]*=(1-f); sh[i]*=(1-f); return v*(1-COST)
    def buy(i,cash,t): sh[i]+=cash*(1-COST)/A[t,i]; cb[i]+=cash
    for t in range(len(idx)):
        if units>0: unit=float(sh@A[t])/units
        if pend is not None:
            k,f=pend; pend=None
            if k=="in":
                total=float(sh@A[t]); amt=sh[src]*A[t,src]*f
                if cap is not None: amt=min(amt, max(0.0, cap*total-sh[3]*A[t,3]))
                if amt>1e-9: buy(3,sell(src,amt/(sh[src]*A[t,src]),t),t); nsw+=1; moved+=amt; ev.append(("in",idx[t]))
            if k in("out","stop") and sh[3]>0: buy(0,sell(3,1.0,t),t); ev.append((k,idx[t])); nstop+=(k=="stop")
        if (lump and t==0) or (not lump and idx[t].month!=month):
            amt=100000.0 if lump else 1000.0
            if newmoney and inlev and not lump:   # 새 돈만 레버리지로
                buy(3,amt,t)
            else:
                for i,wt in (static or {0:1/3,1:1/3,2:1/3}).items(): buy(i,amt*wt,t)
            contrib+=amt; flows.append((idx[t],-amt)); units+=amt/unit
        month=idx[t].month
        if tax and (t==len(idx)-1 or idx[t+1].year!=idx[t].year):
            if realized>0:
                due=realized*TAX; vals=sh*A[t]; s_=0 if vals[0]>due else int(np.argmax(vals)); f=min(1.0,due/vals[s_]); cb[s_]*=(1-f); sh[s_]*=(1-f); taxpaid+=due
            realized=0.0
        unit=float(sh@A[t])/units; uv.append(unit)
        if entry is None: continue
        if not armed and dd[t]>-0.05: armed=True
        if not inlev:
            go=False
            if entry=="dd" and armed and dd[t]<=-x: go=True
            elif entry=="vix" and armed and vix[t]>=x: go=True
            if go: armed=False; inlev=True; pend=("in",1.0) if not newmoney else None
        elif sh[3]>0 and pend is None:
            avg=cb[3]/sh[3]; r=A[t,3]/avg-1
            if stop is not None and r<=-stop: pend=("stop",1.0); inlev=False
            elif exit_[0]=="p" and r>=int(exit_[1:])/100: pend=("out",1.0); inlev=False
    uv=pd.Series(uv,index=idx); final=float(sh@A[-1])
    fl=flows+[(idx[-1],final)]; ts=np.array([(a-fl[0][0]).days/365.25 for a,_ in fl]); cs=np.array([c for _,c in fl]); lo,hi=-0.9,1.0
    for _ in range(80):
        mid=(lo+hi)/2; lo,hi=(mid,hi) if (cs/(1+mid)**ts).sum()>0 else (lo,mid)
    return {"배수":round(final/contrib,2),"IRR":round(mid*100,1),"낙폭":round((uv/uv.cummax()-1).min()*100),"갈아탐":nsw,"손절":nstop,"세금/원금":round(taxpaid/contrib,2),"ev":ev}
PER={"A":"2011-11-01","B":"2006-07-01","C":"1999-04-01"}
def show(title,fn):
    print("\n■",title)
    rows=[]
    for p,st in PER.items():
        r=fn(st); r.pop("ev"); rows.append({"기간":p,**r})
    print(pd.DataFrame(rows).to_string(index=False))
show("기준: 3등분만(목돈)",lambda st:run(st))
show("기준: -20% 즉시 · 전부 · +100% 청산 (지난번 대표)",lambda st:run(st,"dd",0.2,"p100"))
for s in (0.2,0.3,0.4,0.5):
    show(f"1) 손절 -{s:.0%} 붙임 (-20% 진입·+100% 청산)",lambda st,s=s:run(st,"dd",0.2,"p100",stop=s))
for c in (0.10,0.15,0.25):
    show(f"2) 옮기는 금액 상한 = 계좌의 {c:.0%} (-20% 진입·+100% 청산)",lambda st,c=c:run(st,"dd",0.2,"p100",cap=c))
show("3) QLD 대신 QQQM 으로 옮김 (-20% 진입·+100% 청산)",lambda st:run(st,"dd",0.2,"p100",dest="NQ"))
show("3b) QQQM 으로 옮김, +50% 청산",lambda st:run(st,"dd",0.2,"p50",dest="NQ"))
show("4) TQQQ(3배)로 옮김 (-20% 진입·+100% 청산)",lambda st:run(st,"dd",0.2,"p100",dest="L3"))
show("4b) TQQQ, 손절 -40%",lambda st:run(st,"dd",0.2,"p100",dest="L3",stop=0.4))
show("5) 적립식: 3등분만",lambda st:run(st,lump=False))
show("5) 적립식: SCHD 는 두고, 급락 뒤 새로 넣는 돈만 QLD 로(+100% 되면 정상 적립 복귀)",lambda st:run(st,"dd",0.2,"p100",newmoney=True,lump=False))
show("5b) 적립식 지난번 대표(SCHD 전부 옮김)",lambda st:run(st,"dd",0.2,"p100",lump=False))
# 손절 변형의 닷컴 흐름
r=run("1999-04-01","dd",0.2,"p100",stop=0.3); print("\n손절 -30%, C 기간 사건:",[(k,str(t.date())) for k,t in r["ev"]])
r=run("2011-11-01","dd",0.2,"p100",stop=0.3); print("손절 -30%, A 기간 사건:",[(k,str(t.date())) for k,t in r["ev"]])
