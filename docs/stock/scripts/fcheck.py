"""재무 팩터 예측력이 진짜인지 확인: 기간별 안정성, 저가주 효과 제거, 긴 기간, 상하위 10% 격차."""
import numpy as np
import pandas as pd

import ffactors as FF
import qengine as Q
import qsweep as S

pd.set_option("display.width", 200)
NR, NT = FF.NR, FF.NT
TOP = ["주주환원", "자사주수익률", "E/P", "S/P", "EBIT/EV", "CF/P", "FCF/P", "복합:가치", "저주식발행",
       "복합:마법공식", "B/P", "ROA", "복합:퀄리티"]


def fwd(r, h=1):
    r2 = min(r + h, NR - 1)
    i, i2 = Q.RIDX[r], Q.RIDX[r2]
    o, o2 = Q.OPa[i + 1], Q.OPa[i2 + 1]
    g = np.where(np.isfinite(o2) & (o2 > 0), o2 / o, Q.PXf[i2 + 1] / o)
    return np.where(np.isfinite(g) & (g > 0), g - 1, np.nan)


def resid(z, ctrl):
    """횡단면에서 z 에서 ctrl 로 설명되는 부분을 뺀다"""
    out = np.full_like(z, np.nan)
    for r in range(NR):
        m = np.isfinite(z[r]) & np.isfinite(ctrl[r])
        if m.sum() < 30:
            continue
        x, y = ctrl[r, m], z[r, m]
        b = np.cov(x, y)[0, 1] / (np.var(x) + 1e-12)
        out[r, m] = y - b * x
    return out


def ic_series(z, h=1, y0=2011, y1=2100):
    out = []
    for r in range(NR - h):
        yr = Q.REBAL[r].year
        if yr < y0 or yr > y1:
            continue
        g = fwd(r, h)
        m = Q.ELIGM[r] & np.isfinite(z[r]) & np.isfinite(g)
        if m.sum() < 50:
            continue
        out.append(np.corrcoef(pd.Series(z[r, m]).rank(), pd.Series(g[m]).rank())[0, 1])
    a = np.array(out)
    a = a[np.isfinite(a)]
    return a


def fmt(a):
    return f"{a.mean():+.4f}(t{a.mean()/(a.std()/np.sqrt(len(a))):+.1f})" if len(a) > 5 else "   -   "


print("== 1. 기간별 IC (시세 보유율: 2011~14 약 70%, 15~18 약 80%, 19~22 약 90%, 23~26 약 97%) ==")
rows = []
for k in TOP:
    z = FF.Z[k]
    rows.append(dict(팩터=k, **{f"{a}~{b}": fmt(ic_series(z, 1, a, b)) for a, b in [(2011, 2014), (2015, 2018), (2019, 2022), (2023, 2026)]}))
print(pd.DataFrame(rows).to_string(index=False))

print("\n== 2. 저가주 효과를 뺀 뒤 IC (가격 z 로 회귀한 잔차) / 3개월 앞 IC / 12개월 앞 IC ==")
rows = []
for k in TOP:
    z = FF.Z[k]
    zr = resid(z, S.Z["가격"])
    rows.append(dict(팩터=k, 원래=fmt(ic_series(z)), 저가주제거=fmt(ic_series(zr)), 앞3개월=fmt(ic_series(z, 3)), 앞12개월=fmt(ic_series(z, 12))))
print(pd.DataFrame(rows).to_string(index=False))

print("\n== 3. 상위 10% − 하위 10% 월 수익 격차 (비용 전) ==")
rows = []
for k in TOP:
    z = FF.Z[k]
    sp = []
    for r in range(NR - 1):
        if Q.REBAL[r].year < 2011:
            continue
        g = fwd(r)
        m = Q.ELIGM[r] & np.isfinite(z[r]) & np.isfinite(g)
        if m.sum() < 100:
            continue
        zz, gg = z[r, m], g[m]
        hi, lo = np.quantile(zz, .9), np.quantile(zz, .1)
        sp.append(gg[zz >= hi].mean() - gg[zz <= lo].mean())
    sp = np.array(sp)
    rows.append(dict(팩터=k, 월평균격차=f"{sp.mean():+.2%}", t값=f"{sp.mean()/(sp.std()/np.sqrt(len(sp))):+.2f}",
                     양수인달=f"{(sp>0).mean():.0%}", 연환산=f"{sp.mean()*12:+.1%}"))
print(pd.DataFrame(rows).to_string(index=False))
