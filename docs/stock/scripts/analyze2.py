"""후속 분석: 발동조차 안 한 조건을 걸러내고, 앞→뒤 절반 선택이 통한 이유를 캔다."""
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from scipy import stats

import engine as E

pd.set_option("display.width", 260)
df = pd.read_pickle("sweep.pkl")
base = pd.read_pickle("sweep_base.pkl")
PER = ["A", "B", "C", "C1", "C2", "B1", "B2"]
for p in PER:
    df[f"초과_{p}"] = df[f"배수_{p}"] / base[p]["①3등분"]["배수"]

SPAN = {"A": ("2011-11-01", None), "B": ("2006-07-01", None), "C": ("1999-04-01", None),
        "C1": ("1999-04-01", "2013-01-01"), "C2": ("2013-01-01", None),
        "B1": ("2006-07-01", "2016-07-01"), "B2": ("2016-07-01", None)}

print("== 0. 한 번도 갈아타지 않은 조건 ==")
print(f"C 기간(27년) 동안 갈아탐 0회: {(df.갈아탐==0).sum():,}개 ({(df.갈아탐==0).mean():.0%})")
print(f"1회뿐: {(df.갈아탐==1).sum():,}개, 2회 이하: {(df.갈아탐<=2).mean():.0%}")
print("   → 27년에 한두 번 움직이는 규칙은 '전략'이 아니라 동전 한두 번 던지기에 가깝다.\n")

print("== 3b(수정). 노출이 같은 고정 배분과 비교 — 실제로 갈아탄 조건만 ==")
curve = {}
for p in PER:
    st, en = SPAN[p]
    xs, ys = [], []
    for k in np.linspace(0, 1, 26):
        r = E.simulate(st, end=en, static={0: (1 - k) / 3, 3: k / 3, 1: 1 / 3, 2: 1 / 3})
        xs.append(r["노출"]); ys.append(r["배수"])
    o = np.argsort(xs)
    curve[p] = (np.array(xs)[o], np.array(ys)[o])


def matched_ratio(sub, p):
    xs, ys = curve[p]
    inside = (sub[f"노출_{p}"] >= xs[0]) & (sub[f"노출_{p}"] <= xs[-1])
    m = np.interp(sub[f"노출_{p}"], xs, ys)
    return sub[f"배수_{p}"] / m, inside


for p in ["A", "B", "C"]:
    sub = df[(df.dest == "L2") & (df.갈아탐 > 0)]
    r, inside = matched_ratio(sub, p)
    r = r[inside]
    xs, _ = curve[p]
    print(f"  [{p}] 고정배분 노출범위 {xs[0]:.0%}~{xs[-1]:.0%} 안에 드는 QLD 조건 {len(r):,}개: "
          f"중앙값 {r.median():.3f}, 이긴 비율 {(r>1).mean():.0%}, 상위10% {r.quantile(.9):.2f}, 최고 {r.max():.2f}")
print("   (1.00 = 타이밍이 보탠 것이 없음. 낮으면 비용·세금만큼 손해)")

print("\n== 4(수정). 조건별 효과 — '없음'까지 포함 ==")
g = df[df.종류 == "격자"].copy()
for col, nm in [("cap", "금액상한"), ("target", "청산목표"), ("stop", "손절")]:
    k = g[col].astype(object).where(g[col].notna(), "없음").astype(str)
    t = g.groupby(k)[["초과_A", "초과_B", "초과_C"]].median().round(2)
    t["조건수"] = g.groupby(k).size()
    print(f"\n[{nm}]"); print(t.to_string())

print("\n== 5(심화). 앞→뒤 선택이 통한 이유 ==")
for tr, te, nm in [("C1", "C2", "1999~2012 → 2013~2026"), ("B1", "B2", "2006~2016 → 2016~2026")]:
    d = df.copy()
    top = d.nlargest(100, f"초과_{tr}")
    print(f"\n{nm}")
    print(f"  전체 평균 노출({te}) {d[f'노출_{te}'].mean():.0%} vs 앞절반 상위100의 노출({te}) {top[f'노출_{te}'].mean():.0%}")
    print(f"  상위100의 구성: 목적지 {dict(top.dest.value_counts())}, 진입 {dict(top.entry.value_counts())}")
    print(f"  상위100의 진입문턱 중앙값 {top.thr.median():.2f}, 갈아탐 중앙값 {top.갈아탐.median():.0f}회")
    sub = top[top.dest == "L2"]
    if len(sub) > 3:
        r, inside = matched_ratio(sub, te)
        print(f"  상위100 중 QLD {len(sub)}개의 '노출 맞춘 비교'({te}): 중앙값 {r[inside].median():.2f}")
    allq = d[(d.dest == "L2") & (d.갈아탐 > 0)]
    r2, ins2 = matched_ratio(allq, te)
    print(f"  (참고) 전체 QLD 조건의 같은 비교: 중앙값 {r2[ins2].median():.2f}")

print("\n== 8. 진입 횟수와 성적 ==")
t = df.groupby(pd.cut(df.갈아탐, [-1, 0, 1, 2, 4, 8, 16, 999],
                      labels=["0회", "1회", "2회", "3~4회", "5~8회", "9~16회", "17회+"]))
print(t[["초과_C", "초과_A", "낙폭_C", "세금"]].median().round(3).join(t.size().rename("조건수")).to_string())

print("\n== 9. '세 기간 모두 이긴' 조건들은 무엇에 기대고 있나 ==")
allwin = (df.초과_A > 1) & (df.초과_B > 1) & (df.초과_C > 1)
s = df[allwin]
print(f"{len(s):,}개 중 진입기준: {dict(s.entry.value_counts())}")
print(f"  VIX 진입의 문턱 분포: {s[s.entry=='vix'].thr.describe()[['25%','50%','75%','max']].round(1).to_dict()}")
print(f"  갈아탐 횟수 중앙값 {s.갈아탐.median():.0f}회, 그중 2회 이하 {(s.갈아탐<=2).mean():.0%}")
hi = s[s.entry == "vix"]
print(f"  VIX 45 이상에서만 발동하는 조건: {(hi.thr>=45).sum():,}개 — 실제로 VIX 45 이상이던 날은 "
      f"27년 중 {(E.VIX.values>=45).sum()}일({(E.VIX.values>=45).mean():.1%})")
