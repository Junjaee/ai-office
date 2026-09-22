"""재무제표 팩터 만들기. 값이 클수록 '좋다' 방향으로 통일."""
import numpy as np
import pandas as pd

import qengine as Q
import qsweep as S

_d = pd.read_pickle("fpanel.pkl")
P = _d["panel"]
NR, NT = len(Q.REBAL), len(Q.TICK)
PX_RB = Q.PX.reindex(Q.REBAL).values
MC = PX_RB * P["shares"]                       # 시가총액 = 주가 × 공시된 주식수


def sdiv(a, b, pos_den=False):
    b = np.asarray(b, dtype=float)
    ok = np.isfinite(a) & np.isfinite(b) & (b != 0)
    if pos_den:
        ok &= b > 0
    return np.where(ok, a / np.where(ok, b, 1), np.nan)


def z0(a):
    return np.where(np.isfinite(a), a, 0.0)


def zmat(a):
    """재조정일별 횡단면 표준화(후보 종목만), ±3 절단"""
    a = np.where(Q.ELIGM & np.isfinite(a), a, np.nan)
    mu = np.nanmean(a, axis=1, keepdims=True)
    sd = np.nanstd(a, axis=1, keepdims=True)
    return np.clip((a - mu) / np.where(sd > 0, sd, np.nan), -3, 3)


def zavg(*arrs):
    return np.nanmean([zmat(x) for x in arrs], axis=0)


RAW = {}
RAW["E/P"] = sdiv(P["ni"], MC, True)
RAW["B/P"] = sdiv(P["equity"], MC, True)
RAW["S/P"] = sdiv(P["rev"], MC, True)
RAW["CF/P"] = sdiv(P["ocf"], MC, True)
RAW["FCF/P"] = sdiv(P["ocf"] - z0(P["capex"]), MC, True)
EV = MC + z0(P["ltdebt"]) - z0(P["cash"])
RAW["EBIT/EV"] = sdiv(P["oi"], EV, True)
RAW["ROE"] = sdiv(P["ni"], P["equity"], True)
RAW["ROA"] = sdiv(P["ni"], P["assets"], True)
RAW["GP/A"] = sdiv(P["gp"], P["assets"], True)
RAW["매출총이익률"] = sdiv(P["gp"], P["rev"], True)
RAW["영업이익률"] = sdiv(P["oi"], P["rev"], True)
RAW["저발생액"] = -sdiv(P["ni"] - P["ocf"], P["assets"], True)
RAW["저부채"] = -sdiv(P["liab"], P["assets"], True)
RAW["저자산성장"] = -(sdiv(P["assets"], P["assets_1y"], True) - 1)
RAW["매출성장"] = sdiv(P["rev"], P["rev_1y"], True) - 1
RAW["이익성장"] = sdiv(P["ni"] - P["ni_1y"], np.abs(P["ni_1y"]), True)
RAW["배당수익률"] = sdiv(z0(P["div"]), MC, True)
RAW["자사주수익률"] = sdiv(z0(P["buyback"]), MC, True)
RAW["주주환원"] = sdiv(z0(P["div"]) + z0(P["buyback"]), MC, True)
RAW["저주식발행"] = -(sdiv(P["shares"], P["shares_1y"], True) - 1)
RAW["소형주"] = -np.log(np.where(MC > 0, MC, np.nan))
RAW["대형주"] = -RAW["소형주"]
IC_ = z0(P["ppe"]) + z0(P["curassets"]) - z0(P["curliab"])
RAW["ROIC"] = sdiv(P["oi"], IC_, True)
RAW["R&D/매출"] = sdiv(z0(P["rnd"]), P["rev"], True)
RAW["이자보상"] = np.clip(sdiv(P["oi"], P["intexp"], True), -50, 50)
RAW["저EV/EBITDA"] = sdiv(P["oi"] + z0(P["da"]), EV, True)

# F-스코어(6항목 축약): 1점씩
f = np.zeros((NR, NT))
f += (RAW["ROA"] > 0)
f += (P["ocf"] > 0)
f += (P["ocf"] > P["ni"])
f += (sdiv(P["ni"], P["assets"], True) > sdiv(P["ni_1y"], P["assets_1y"], True))
f += (sdiv(P["liab"], P["assets"], True) < sdiv(P["liab_1y"], P["assets_1y"], True))
f += (P["shares"] <= P["shares_1y"] * 1.001)
f += (sdiv(P["gp"], P["rev"], True) > sdiv(P["gp_1y"], P["rev_1y"], True))
core = np.isfinite(RAW["ROA"]) & np.isfinite(P["ocf"]) & np.isfinite(P["shares_1y"])
RAW["F스코어"] = np.where(core, f, np.nan)

Z = {k: zmat(v) for k, v in RAW.items()}
Z["복합:가치"] = zavg(RAW["E/P"], RAW["B/P"], RAW["S/P"], RAW["CF/P"])
Z["복합:퀄리티"] = zavg(RAW["ROA"], RAW["GP/A"], RAW["저발생액"], RAW["저부채"])
Z["복합:가치+퀄리티"] = np.nanmean([Z["복합:가치"], Z["복합:퀄리티"]], axis=0)
Z["복합:마법공식"] = zavg(RAW["EBIT/EV"], RAW["ROIC"])
Z["복합:성장"] = zavg(RAW["매출성장"], RAW["이익성장"])
Z["복합:주주환원+가치"] = zavg(RAW["주주환원"], RAW["E/P"])
Z["복합:가치+모멘텀"] = np.nanmean([Z["복합:가치"], S.Z["모멘텀12-1"]], axis=0)
Z["복합:퀄리티+모멘텀"] = np.nanmean([Z["복합:퀄리티"], S.Z["모멘텀12-1"]], axis=0)
Z["복합:퀄리티+저변동성"] = np.nanmean([Z["복합:퀄리티"], S.Z["저변동성252"]], axis=0)
Z["복합:F스코어+가치"] = zavg(RAW["F스코어"], RAW["B/P"])

if __name__ == "__main__":
    print(f"재무 팩터 {len(Z)}개")
    cov = pd.Series(((np.isfinite(RAW["E/P"]) & Q.ELIGM).sum(1) / Q.ELIGM.sum(1)), index=Q.REBAL)
    print("E/P 보유율:", "  ".join(f"{y.year}:{v:.0%}" for y, v in cov.resample("YE").mean().items() if y.year % 2 == 1))
    # 신호별 IC
    rows = []
    for k, z in Z.items():
        cc = []
        for r in range(NR - 1):
            v = Q.ELIGM[r] & np.isfinite(z[r]) & np.isfinite(S.Z["모멘텀12-1"][r])
            if v.sum() < 50 or Q.REBAL[r].year < 2011:
                continue
            fwd = np.full(NT, np.nan)
            i, i2 = Q.RIDX[r], Q.RIDX[min(r + 1, NR - 1)]
            g = np.where(np.isfinite(Q.OPa[i2 + 1]) & (Q.OPa[i2 + 1] > 0), Q.OPa[i2 + 1] / Q.OPa[i + 1], Q.PXf[i2 + 1] / Q.OPa[i + 1])
            m = v & np.isfinite(g)
            cc.append(np.corrcoef(pd.Series(z[r, m]).rank(), pd.Series(g[m]).rank())[0, 1])
        cc = np.array(cc)
        rows.append((k, np.nanmean(cc), np.nanmean(cc) / (np.nanstd(cc) / np.sqrt(np.isfinite(cc).sum())), int(np.isfinite(cc).sum())))
    t = pd.DataFrame(rows, columns=["팩터", "IC", "t값", "개월"]).sort_values("IC", key=abs, ascending=False)
    print("\n각 재무 팩터가 다음 달 종목 순위를 얼마나 맞혔나 (2011~, |t|>2 면 의미 있음)")
    print(t.round(4).to_string(index=False))
