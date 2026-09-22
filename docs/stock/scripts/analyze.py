"""대규모 탐색 결과 분석: 1등 찾기가 아니라 '고를 수 있는가'를 잰다."""
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
from scipy import stats

pd.set_option("display.width", 250)

df = pd.read_pickle("sweep.pkl")
base = pd.read_pickle("sweep_base.pkl")
PER = ["A", "B", "C", "C1", "C2", "B1", "B2"]
for p in PER:
    df[f"초과_{p}"] = df[f"배수_{p}"] / base[p]["①3등분"]["배수"]

print(f"조건 {len(df):,}개 (격자 {(df.종류=='격자').sum():,} + 무작위 {(df.종류=='무작위').sum():,})\n")

print("== 1. 기준선 ==")
b = pd.DataFrame({k: {p: round(base[p][k]["배수"], 2) for p in PER} for k in base["A"]}).T
print(b.to_string())

print("\n== 2. 조건 전체의 분포 (① 3등분만 = 1.00) ==")
rows = []
for p in ["A", "B", "C"]:
    s = df[f"초과_{p}"]
    rows.append({"기간": p, "중앙값": s.median(), "상위10%": s.quantile(.9), "최고": s.max(),
                 "최저": s.min(), "①을 이긴 비율": (s > 1).mean(),
                 "④(늘2배)를 이긴 비율": (df[f"배수_{p}"] > base[p]["④늘2배"]["배수"]).mean()})
print(pd.DataFrame(rows).round(3).to_string(index=False))
allwin = ((df["초과_A"] > 1) & (df["초과_B"] > 1) & (df["초과_C"] > 1))
print(f"\nA·B·C 세 기간 모두에서 ①을 이긴 조건: {allwin.sum():,}개 ({allwin.mean():.1%})")
print(f"그중 낙폭이 ① 이하인 것: {(allwin & (df.낙폭_C >= base['C']['①3등분']['낙폭'])).sum():,}개")

print("\n== 3. 성적은 조건 덕인가, 레버리지를 오래 든 덕인가 ==")
for p in ["A", "C"]:
    x, y = df[f"노출_{p}"].values, np.log(df[f"배수_{p}"].clip(lower=.01)).values
    ok = np.isfinite(x) & np.isfinite(y)
    for lbl, sub in [("전체", ok), ("2배(QLD)만", ok & (df.dest == "L2").values)]:
        if sub.sum() < 50:
            continue
        r = stats.pearsonr(x[sub], y[sub])[0]
        sl = np.polyfit(x[sub], y[sub], 2)
        pred = np.polyval(sl, x[sub])
        r2 = 1 - ((y[sub] - pred) ** 2).sum() / ((y[sub] - y[sub].mean()) ** 2).sum()
        print(f"  {p} {lbl:10s}: 노출과 로그배수의 상관 {r:.3f}, 노출만으로 설명되는 비율 R2={r2:.3f}")

print("\n== 3b. 노출이 같은 '판단 없는 배분'과 비교 ==")
print("   배당몫(1/3) 중 일부를 늘 레버리지로 두는 고정 배분을 0%~100% 로 바꿔 가며 곡선을 만들고,")
print("   각 조건을 '자기와 노출이 같은 고정 배분'과 견준다. 1.00 보다 크면 타이밍이 보탠 것.")
import engine as E

curve = {}
for p in ["A", "B", "C"]:
    st, en = {"A": ("2011-11-01", None), "B": ("2006-07-01", None), "C": ("1999-04-01", None)}[p]
    xs, ys = [], []
    for k in np.linspace(0, 1, 21):
        r = E.simulate(st, end=en, static={0: (1 - k) / 3, 3: k / 3, 1: 1 / 3, 2: 1 / 3})
        xs.append(r["노출"]); ys.append(r["배수"])
    o = np.argsort(xs)
    curve[p] = (np.array(xs)[o], np.array(ys)[o])
    print(f"   [{p}] 고정 배분 곡선: 노출 {xs[0]:.0%}→{xs[-1]:.0%} 일 때 배수 {ys[0]:.1f}→{ys[-1]:.1f}")

for p in ["A", "B", "C"]:
    xs, ys = curve[p]
    sub = df[df.dest == "L2"]
    matched = np.interp(sub[f"노출_{p}"], xs, ys)
    ratio = sub[f"배수_{p}"] / matched
    print(f"   [{p}] QLD 조건 {len(sub):,}개: 노출이 같은 고정 배분 대비 중앙값 {ratio.median():.3f}, "
          f"이긴 비율 {(ratio>1).mean():.0%}, 상위10% {ratio.quantile(.9):.2f}")

print("\n== 4. 조건별 효과 (격자 탐색, 기간별 초과수익 중앙값) ==")
g = df[df.종류 == "격자"]
for col, nm in [("dest", "목적지"), ("entry", "진입기준"), ("confirm", "회복확인"), ("frac", "옮기는비율"),
                ("cap", "금액상한"), ("target", "청산목표"), ("stop", "손절")]:
    t = g.groupby(g[col].astype(str))[["초과_A", "초과_B", "초과_C"]].median().round(2)
    t["조건수"] = g.groupby(g[col].astype(str)).size()
    print(f"\n[{nm}]"); print(t.to_string())

print("\n[진입 문턱 세분화 — 고점대비 하락(dd), 목적지 QLD]")
t = g[(g.entry == "dd") & (g.dest == "L2")].groupby("thr")[["초과_A", "초과_B", "초과_C"]].median().round(2)
print(t.to_string())

print("\n== 5. 앞 절반에서 고른 조건이 뒤 절반에서도 통하는가 ==")
for tr, te, nm in [("C1", "C2", "1999~2012 → 2013~2026"), ("B1", "B2", "2006~2016 → 2016~2026")]:
    d = df.dropna(subset=[f"초과_{tr}", f"초과_{te}"]).copy()
    d["훈련순위"] = d[f"초과_{tr}"].rank(pct=True)
    d["시험순위"] = d[f"초과_{te}"].rank(pct=True)
    rho = stats.spearmanr(d[f"초과_{tr}"], d[f"초과_{te}"]).statistic
    print(f"\n{nm}  (조건 {len(d):,}개)")
    print(f"  앞·뒤 순위 상관: {rho:+.3f}  (1이면 완벽히 이어짐, 0이면 무관)")
    for k in (1, 10, 100, 1000):
        top = d.nlargest(k, f"초과_{tr}")
        print(f"  앞에서 1등~{k}위를 고르면 → 뒤 절반 순위 백분위 중앙값 {top['시험순위'].median():.0%}, "
              f"뒤 절반에서 ①을 이긴 비율 {(top[f'초과_{te}']>1).mean():.0%}, "
              f"뒤 절반 초과 중앙값 {top[f'초과_{te}'].median():.2f}")
    print(f"  (참고) 전체 조건의 뒤 절반: ①을 이긴 비율 {(d[f'초과_{te}']>1).mean():.0%}, 초과 중앙값 {d[f'초과_{te}'].median():.2f}")

print("\n== 6. 전체 1등과 그 조건의 다른 기간 성적 ==")
for p in ["A", "C"]:
    best = df.loc[df[f"초과_{p}"].idxmax()]
    print(f"\n[{p} 기준 1등] {best.dest} {best.entry} {best.thr} 확인{best.confirm} 비율{best.frac} "
          f"상한{best.cap} 목표{best.target} 손절{best.stop} 추적{best.trail} 기한{best.maxdays}")
    print("   " + "  ".join(f"{q}: {best[f'초과_{q}']:.2f}배" for q in ["A", "B", "C"])
          + f"  | 낙폭_C {best.낙폭_C:.0%} 노출_C {best.노출_C:.0%} 갈아탐 {best.갈아탐}회")

print("\n== 7. 세 기간 모두 ①을 이기고 낙폭도 ① 이하인 조건 ==")
safe = df[allwin & (df.낙폭_A >= base["A"]["①3등분"]["낙폭"]) & (df.낙폭_C >= base["C"]["①3등분"]["낙폭"])]
print(f"{len(safe):,}개")
if len(safe):
    print(safe.groupby("dest").size().to_string())
    print(safe[["dest", "entry", "thr", "frac", "cap", "target", "stop", "초과_A", "초과_B", "초과_C",
                "낙폭_C", "노출_C"]].nlargest(12, "초과_C").round(3).to_string(index=False))
