import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, itertools, sys
pd.set_option("display.width",250)
d=pd.read_pickle("etf.pkl")
def splice(new,old):
    r=d[new].pct_change().where(d[new].notna()&d[new].shift().notna(), d[old].pct_change()); return (1+r.fillna(0)).cumprod()
rf=(d["^IRX"].ffill()/100).fillna(0.02)
d["SYN"]=(1+(2*d["QQQ"].pct_change()-(0.0095+rf)/252).fillna(0)).cumprod()
P=pd.DataFrame({"DIV":splice("SCHD","VEIPX"),"SP":d["SPY"],"NQ":d["QQQ"],"LEV":splice("QLD","SYN")})[d["QQQ"].notna()]
VIX=d["^VIX"].reindex(P.index).ffill(); HI=P["NQ"].rolling(252,min_periods=1).max(); MA50=P["NQ"].rolling(50).mean()
COST,TAX,LV=0.003,0.22,[0.15,0.25,0.35]

def run(start,entry=None,x=0.2,frac=1.0,exit_="p100",tax=True,static=None,lump=False):
    m=P.index>=start; idx=P.index[m]; A=P.values[m]; nq=A[:,2]; dd=nq/HI.values[m]-1; ma=MA50.values[m]; vix=VIX.values[m]
    sh=np.zeros(4); cb=np.zeros(4); units=0.0; unit=1.0; contrib=0.0; flows=[]; uv=[]; realized=0.0; taxpaid=0.0
    inlev=False; armed=True; seen=False; rung=0; pend=None; nsw=0; month=None; lev_days=0
    def sell(i,f,t):
        nonlocal realized
        v=sh[i]*A[t,i]*f; realized+=v-cb[i]*f; cb[i]*=(1-f); sh[i]*=(1-f); return v*(1-COST)
    def buy(i,cash,t): sh[i]+=cash*(1-COST)/A[t,i]; cb[i]+=cash
    for t in range(len(idx)):
        if units>0: unit=float(sh@A[t])/units
        if pend is not None:                       # 어제 신호 → 오늘 종가 실행
            k,f=pend; pend=None
            if k=="in" and sh[0]>0: buy(3,sell(0,f,t),t); nsw+=1
            if k=="out" and sh[3]>0: buy(0,sell(3,1.0,t),t)
        if (lump and t==0) or (not lump and idx[t].month!=month):
            amt=100000.0 if lump else 1000.0
            for i,wt in (static or {0:1/3,1:1/3,2:1/3}).items(): buy(i,amt*wt,t)
            contrib+=amt; flows.append((idx[t],-amt)); units+=amt/unit
        month=idx[t].month
        if tax and (t==len(idx)-1 or idx[t+1].year!=idx[t].year):
            if realized>0:
                due=realized*TAX; vals=sh*A[t]; src=0 if vals[0]>due else int(np.argmax(vals)); f=min(1.0,due/vals[src]); cb[src]*=(1-f); sh[src]*=(1-f); taxpaid+=due
            realized=0.0
        unit=float(sh@A[t])/units; uv.append(unit); lev_days+=sh[3]>0
        if entry is None: continue
        if not armed and dd[t]>-0.05: armed=True; seen=False; rung=0
        if not inlev or exit_=="hold":
            go=None
            if entry=="dd" and armed and dd[t]<=-x: go=frac; armed=False
            elif entry=="ddma":
                if dd[t]<=-x: seen=True
                if armed and seen and nq[t]>ma[t]: go=frac; armed=False
            elif entry=="vix" and armed and vix[t]>=x: go=frac; armed=False
            elif entry=="ladder" and armed and rung<3 and dd[t]<=-LV[rung]: go=1/(3-rung); rung+=1
            if go and sh[0]>0: pend=("in",go); inlev=True
        elif entry=="ladder" and rung<3 and dd[t]<=-LV[rung]: pend=("in",1/(3-rung)); rung+=1
        if inlev and exit_!="hold" and pend is None and sh[3]>0:
            avg=cb[3]/sh[3]
            if (exit_[0]=="p" and A[t,3]>=avg*(1+int(exit_[1:])/100)) or (exit_=="hi" and dd[t]>=-0.01):
                pend=("out",1.0); inlev=False; armed=False
    uv=pd.Series(uv,index=idx); final=float(sh@A[-1])
    fl=flows+[(idx[-1],final)]; ts=np.array([(a-fl[0][0]).days/365.25 for a,_ in fl]); cs=np.array([c for _,c in fl]); lo,hi=-0.9,1.0
    for _ in range(80):
        mid=(lo+hi)/2; lo,hi=(mid,hi) if (cs/(1+mid)**ts).sum()>0 else (lo,mid)
    return {"배수":final/contrib,"IRR":mid,"낙폭":(uv/uv.cummax()-1).min(),"전환":nsw,"레버리지보유비율":lev_days/len(idx),"세금/원금":taxpaid/contrib,"끝에2배비중":sh[3]*A[-1,3]/final,"uv":uv}

PER={"A":("2011-11-01","2011-11~ SCHD·QLD 실물"),"B":("2006-07-01","2006-07~ 2008년 포함(배당은 대역)"),"C":("1999-04-01","1999-04~ 닷컴 포함(배당·2배 대역)")}
NAME=lambda e,x,f:{"dd":f"1년고점 -{x:.0%} 즉시","ddma":f"-{x:.0%} 찍고 50일선 회복","ladder":"3단 분할 -15/-25/-35","vix":f"VIX {x:.0f} 이상"}[e]+("" if e=="ladder" else f" ·배당의 {f:.0%}")
grid=[("dd",x,f) for x in (0.15,0.20,0.25,0.30) for f in (0.5,1.0)]+[("ddma",0.20,1.0),("ddma",0.30,1.0),("ladder",0,1.0),("vix",35,1.0),("vix",45,1.0)]
EX=[("p50","+50%에 청산"),("p100","+100%에 청산"),("hi","1년 신고가에 청산"),("hold","안 팔고 보유")]
for lump in (False,True):
    rows=[]
    for p,(st,desc) in PER.items():
        print(f"\n==== [{p}] {desc} — {'목돈 한 번에' if lump else '매월 적립'}")
        B={"① 3등분만":{}, "② 전부 S&P500":dict(static={1:1.0}), "③ 전부 나스닥100":dict(static={2:1.0}), "④ 배당 몫을 늘 2배ETF로":dict(static={3:1/3,1:1/3,2:1/3})}
        bres={k:run(st,lump=lump,**kw) for k,kw in B.items()}
        print("   "+" / ".join(f"{k} {r['배수']:.2f}배·연{r['IRR']:.1%}·낙폭{r['낙폭']:.0%}" for k,r in bres.items()))
        for (e,x,f),(ek,en) in itertools.product(grid,EX):
            r=run(st,e,x,f,ek,lump=lump); r.pop("uv"); rows.append({"기간":p,"진입":NAME(e,x,f),"청산":en,**r})
        s=pd.DataFrame([r for r in rows if r["기간"]==p]); b0=bres["① 3등분만"]
        print(f"   변형 {len(s)}개: 배수 중앙값 {s.배수.median():.2f}(최저 {s.배수.min():.2f}~최고 {s.배수.max():.2f}) | ①을 이긴 비율 {(s.배수>b0['배수']).mean():.0%} | 낙폭 중앙값 {s.낙폭.median():.0%}(최악 {s.낙폭.min():.0%}) | ④보다 배수 높은 변형 {(s.배수>bres['④ 배당 몫을 늘 2배ETF로']['배수']).sum()}개")
        s2=s[~s.진입.str.contains("50%")]
        t=s2.assign(v=s2.배수.round(2).astype(str)+"/"+(s2.낙폭*100).round(0).astype(int).astype(str)+"%").pivot(index="진입",columns="청산",values="v")[[n for _,n in EX]]
        t["전환횟수"]=s2[s2.청산=="+100%에 청산"].set_index("진입").전환; t["2배 보유일 비율"]=(s2[s2.청산=="+100%에 청산"].set_index("진입").레버리지보유비율*100).round(0).astype(int).astype(str)+"%"
        print(t.to_string())
    pd.DataFrame(rows).to_pickle("rot_lump.pkl" if lump else "rot_dca.pkl")
