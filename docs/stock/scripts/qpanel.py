"""머신러닝·딥러닝용 자료 만들기.

각 재조정일 × 종목마다: 특징(신호 20종) + 과거 60일 수익률 + 정답(다음 달 상대수익)
정답은 '다음 달 시가에 사서 그다음 달 시가에 판' 실제 수익에서 그달 평균을 뺀 값.
"""
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

import qengine as Q
import qsweep as S

FEATS = [k for k in S.Z if not k.startswith("복합")]
NR, NT = len(Q.REBAL), len(Q.TICK)

X = np.stack([S.Z[f] for f in FEATS], axis=2).astype(np.float32)   # (재조정, 종목, 특징)
MASK = Q.ELIGM.copy()

# 정답: 다음 달 시가→그다음 달 시가 수익
FWD = np.full((NR, NT), np.nan, dtype=np.float32)
for k in range(NR - 1):
    i, i2 = Q.RIDX[k], Q.RIDX[k + 1]
    o, o2 = Q.OPa[i + 1], Q.OPa[i2 + 1]
    last = Q.PXf[i2 + 1]
    g = np.where(np.isfinite(o2) & (o2 > 0), o2 / o, last / o)
    FWD[k] = np.where(np.isfinite(g) & (g > 0), g - 1, np.nan)

# 과거 60일 수익률 묶음 (딥러닝 순차 모델용)
L = 60
SEQ = np.full((NR, NT, L), np.nan, dtype=np.float32)
Ra = Q.RETa
for k in range(NR):
    i = Q.RIDX[k]
    SEQ[k] = Ra[i - L + 1:i + 1].T

VALID = MASK & np.isfinite(FWD) & np.isfinite(X).all(axis=2) & np.isfinite(SEQ).all(axis=2)


def cs_z(a, valid):
    """재조정일별 횡단면 표준화"""
    out = np.full_like(a, np.nan, dtype=np.float32)
    for k in range(a.shape[0]):
        v = valid[k]
        if v.sum() < 20:
            continue
        x = a[k, v]
        out[k, v] = (x - x.mean()) / (x.std() + 1e-9)
    return out


Y = np.clip(cs_z(FWD, VALID), -4, 4)          # 정답(상대 성적)
YEARS = np.array([d.year for d in Q.REBAL])

if __name__ == "__main__":
    print(f"재조정 {NR}회 × 종목 {NT}개, 특징 {len(FEATS)}개")
    print(f"학습에 쓸 수 있는 칸(종목-월): {int(VALID.sum()):,}개 "
          f"(월평균 {VALID.sum()/NR:.0f}개)")
    print(f"연도별 칸 수: " + " ".join(f"{y}:{int(VALID[YEARS==y].sum())}" for y in range(2006, 2027, 4)))
    print(f"정답 분포: 평균 {np.nanmean(Y):.3f} 표준편차 {np.nanstd(Y):.3f}")
    ic = []
    for f in FEATS:
        z = S.Z[f]
        v = VALID & np.isfinite(z)
        cc = [np.corrcoef(pd.Series(z[k, v[k]]).rank(), pd.Series(FWD[k, v[k]]).rank())[0, 1]
              for k in range(NR) if v[k].sum() > 30]
        ic.append((f, np.mean(cc), np.mean(cc) / (np.std(cc) / np.sqrt(len(cc)))))
    t = pd.DataFrame(ic, columns=["신호", "월평균 순위상관(IC)", "t값"]).sort_values("월평균 순위상관(IC)", key=abs, ascending=False)
    print("\n각 신호가 다음 달 성적과 얼마나 맞았나 (IC, |t|>2 면 통계적으로 의미 있음)")
    print(t.round(3).to_string(index=False))
