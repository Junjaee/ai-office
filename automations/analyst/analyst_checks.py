"""주식 분석 — 점검표 7가지와 판 한 줄(순수). 문턱값은 rules.yaml 한 곳(설계서 §5.1).

상태: pass(통과) · care(주의) · warn(경고) · na(자료 없음/해당 없음).
절대 숫자 대신 같은 업종 중앙값과 견준다. 업종 안 종목이 sector_min 미만이면 시장 전체 중앙값.
"""
from __future__ import annotations

from pathlib import Path
from statistics import median

import yaml

HERE = Path(__file__).resolve().parent
KEYS = ["가치", "매출 성장", "이익 방향", "수익성", "빚", "현금흐름", "추세"]


def load_rules(path: str | Path | None = None) -> dict:
    with open(path or HERE / "rules.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _med(values: list) -> float | None:
    xs = [v for v in values if v is not None]
    return round(median(xs), 2) if xs else None


def medians(records: list[dict], sector_min: int = 5) -> dict:
    """시장 전체와 업종별 중앙값(예상 PER 은 흑자인 것만, 영업이익률은 전부)."""
    def pack(rs):
        return {"fpe": _med([r.get("fpe") for r in rs if (r.get("fpe") or 0) > 0]), "opm": _med([r.get("opm") for r in rs]), "n": len(rs)}
    sectors: dict[str, list] = {}
    for r in records:
        sectors.setdefault(r.get("sector") or "", []).append(r)
    allp = pack(records)
    return {"all": {"fpe": allp["fpe"], "opm": allp["opm"]}, "sector": {k: pack(v) for k, v in sectors.items() if k}}


def ref_for(rec: dict, med: dict, sector_min: int) -> dict:
    """이 종목이 견줄 중앙값과 그 이름(업종 | 시장)."""
    s = (med.get("sector") or {}).get(rec.get("sector") or "")
    if s and s.get("n", 0) >= sector_min and s.get("fpe") is not None:
        return {"fpe": s["fpe"], "opm": s.get("opm"), "label": "업종"}
    return {"fpe": med["all"].get("fpe"), "opm": med["all"].get("opm"), "label": "시장"}


def _eok(v: float, currency: str | None = None) -> str:
    return f"{abs(v) / 1e8:,.0f}억 {'원' if currency == 'KRW' else '달러'}"


def run_checks(rec: dict, med: dict, rules: dict) -> list[dict]:
    ck = rules["checks"]
    ref = ref_for(rec, med, rules.get("sector_min", 5))
    out: list[dict] = []

    def add(key, state, text):
        out.append({"key": key, "state": state, "text": text})

    # 가치
    f, base = rec.get("fpe"), ref["fpe"]
    if f is None or base is None:
        add("가치", "na", "예상 이익 자료 없음")
    elif f <= 0:
        add("가치", "warn", "예상 이익이 적자")
    else:
        ratio = f / base
        tail = f"예상 PER {f:.1f}배 · {ref['label']} 중앙값 {base:.1f}배"
        if ratio < ck["value"]["pass_below"]:
            add("가치", "pass", tail + "보다 낮음")
        elif ratio >= ck["value"]["warn_at"]:
            add("가치", "warn", tail + f"의 {ck['value']['warn_at']}배 이상")
        else:
            add("가치", "care", tail + " 근처")

    # 매출 성장
    g = rec.get("rev_g")
    if g is None:
        add("매출 성장", "na", "자료 없음")
    else:
        state = "pass" if g >= ck["growth"]["pass_at"] else "care" if g >= ck["growth"]["care_at"] else "warn"
        add("매출 성장", state, f"최근 분기 매출 {g:+.1f}% (전년 대비)")

    # 이익 방향
    e = rec.get("eps_g")
    if e is None:
        add("이익 방향", "na", "자료 없음")
    else:
        state = "pass" if e > 0 else "care" if e >= ck["earnings"]["care_floor"] else "warn"
        add("이익 방향", state, f"최근 분기 이익 {e:+.1f}% (전년 대비)")

    # 수익성
    o, obase = rec.get("opm"), ref.get("opm")
    if o is None:
        add("수익성", "na", "자료 없음")
    elif o < 0:
        add("수익성", "warn", f"영업이익률 {o:.1f}% (영업적자)")
    elif obase is not None and o < obase:
        add("수익성", "care", f"영업이익률 {o:.1f}% · {ref['label']} 중앙값 {obase:.1f}%보다 낮음")
    else:
        add("수익성", "pass", f"영업이익률 {o:.1f}%" + (f" · {ref['label']} 중앙값 {obase:.1f}% 이상" if obase is not None else ""))

    # 빚 · 현금흐름 (금융업은 재는 방식이 달라 뺀다)
    if rec.get("financial"):
        add("빚", "na", "금융업은 해당 없음")
        add("현금흐름", "na", "금융업은 해당 없음")
    else:
        d = rec.get("net_debt_ebitda")
        if d is None:
            add("빚", "na", "자료 없음")
        elif d <= 0:
            add("빚", "pass", "빚보다 현금이 많음")
        else:
            state = "pass" if d < ck["debt"]["pass_below"] else "warn" if d >= ck["debt"]["warn_at"] else "care"
            add("빚", state, f"순부채가 연간 영업이익의 {d:.1f}배")
        fcf, ocf = rec.get("fcf"), rec.get("ocf")
        if fcf is None:
            add("현금흐름", "na", "자료 없음")
        elif fcf > 0:
            add("현금흐름", "pass", f"최근 12개월 쓰고 남은 현금 +{_eok(fcf, rec.get("currency"))}")
        elif ocf is not None and ocf > 0:
            add("현금흐름", "care", f"쓰고 남은 현금 −{_eok(fcf, rec.get("currency"))} (영업현금은 흑자)")
        else:
            add("현금흐름", "warn", f"최근 12개월 쓰고 남은 현금 −{_eok(fcf, rec.get("currency"))}")

    # 추세
    off = rec.get("off_hi_pct")
    if off is None:
        add("추세", "na", "자료 없음")
    else:
        state = "pass" if off > -ck["trend"]["pass_within"] else "care" if off > -ck["trend"]["care_within"] else "warn"
        add("추세", state, f"1년 최고가 대비 {off:+.1f}%")
    return out


def diag(checks: list[dict]) -> str:
    good = [c["key"] for c in checks if c["state"] == "pass"]
    bad = [c["key"] for c in checks if c["state"] == "warn"]
    parts = []
    if good:
        parts.append("좋음: " + "·".join(good))
    if bad:
        parts.append("경고: " + "·".join(bad))
    return " / ".join(parts) or "눈에 띄는 항목 없음"


def board_row(rec: dict, checks: list[dict], lens: list[dict] | None = None) -> dict:
    n = {s: sum(1 for c in checks if c["state"] == s) for s in ("pass", "care", "warn")}
    return {"t": rec["t"], "name": rec["name"], "price": rec["price"], "chg_pct": rec.get("chg_pct"), "spark": rec.get("spark") or [],
            "ath_pct": rec.get("ath_pct"), "off_hi_pct": rec.get("off_hi_pct"), "fpe": rec.get("fpe"),
            "n_pass": n["pass"], "n_care": n["care"], "n_warn": n["warn"], "diag": diag(checks), "next_earn": rec.get("next_earn"),
            "warn_keys": [c["key"] for c in checks if c["state"] == "warn"],
            "sector": rec.get("sector") or "", "rev_g": rec.get("rev_g"), "nde": rec.get("net_debt_ebitda"), "dv_ratio": rec.get("dv_ratio"),
            "lenses": list(lens or [])}


LENS_ORDER = ["value", "growth", "event", "flow"]
LENS_LABEL = {"value": "싸고 탄탄", "growth": "실적 개선", "event": "사건", "flow": "돈 몰림"}


def _md(iso: str) -> str:
    _, m, d = iso.split("-")
    return f"{int(m)}월 {int(d)}일"


def lenses(rec: dict, checks: list[dict], events: list[dict], rules: dict) -> list[dict]:
    """발굴 네 관점 중 이 종목이 걸린 것과 이유 한 줄(설계서 §5.2). LENS_ORDER 순."""
    L = rules["lenses"]
    st = {c["key"]: c for c in checks}
    out: list[dict] = []
    if all((st.get(k) or {}).get("state") == "pass" for k in ("가치", "빚", "현금흐름")):
        out.append({"id": "value", "why": f"{st['가치']['text']} · 빚·현금흐름 통과"})
    g, e = rec.get("rev_g"), rec.get("eps_g")
    if g is not None and e is not None and g >= L["growth"]["rev_at"] and e > 0:
        out.append({"id": "growth", "why": f"매출 {g:+.1f}% · 이익 {e:+.1f}% (전년 대비)"})
    major = [x for x in events or [] if x.get("kind") in L["event"]["major"]]
    chg, dv1 = rec.get("chg_pct"), rec.get("dv1_ratio")
    if major:
        more = f" 외 {len(major) - 1}건" if len(major) > 1 else ""
        out.append({"id": "event", "why": f"{_md(major[0]['date'])} {major[0]['kind']} 공시{more}"})
    elif chg is not None and dv1 is not None and abs(chg) >= L["event"]["move_pct"] and dv1 >= L["event"]["dv1_at"]:
        out.append({"id": "event", "why": f"하루 {chg:+.1f}% · 거래대금 평소의 {dv1:.1f}배"})
    dv = rec.get("dv_ratio")
    if dv is not None and dv >= L["flow"]["dv_at"] and rec.get("above_ma20"):
        out.append({"id": "flow", "why": f"최근 5일 거래대금 평소의 {dv:.1f}배 · 20일 평균 위"})
    return out


def lens_info(rules: dict, filings_ok: bool = True) -> dict:
    """관점 이름과 화면에 적을 기준 한 줄 — 문턱값은 rules.yaml 에서 읽어 문장에 끼운다. 공시를 못 받은 날은 사건 기준에 그렇게 적는다."""
    L = rules["lenses"]
    rule = {
        "value": "점검표의 가치·빚·현금흐름이 모두 통과",
        "growth": f"최근 분기 매출이 전년보다 {L['growth']['rev_at']}% 이상 늘고 이익도 늘어남",
        "event": f"최근 {L['event']['days']}일 안에 주요 공시가 있었거나, 기준일 하루에 ±{L['event']['move_pct']}% 이상 움직이면서 거래대금이 평소의 {L['event']['dv1_at']}배 이상"
                 + ("" if filings_ok else " (오늘은 공시를 확인하지 못해 가격 조건만 봤습니다)"),
        "flow": f"최근 5일 평균 거래대금이 60일 평균의 {L['flow']['dv_at']}배 이상이고 종가가 20일 평균 위",
    }
    return {k: {"label": LENS_LABEL[k], "rule": rule[k]} for k in LENS_ORDER}


def peers(rec: dict, records: list[dict], n: int = 3) -> list[dict]:
    """같은 업종에서 덩치(시가총액)가 가장 비슷하고 예상 PER 이 있는 회사 n 개."""
    me = rec.get("mcap") or 0
    pool = [r for r in records if r["t"] != rec["t"] and r.get("sector") == rec.get("sector") and (r.get("fpe") or 0) > 0 and r.get("mcap")]
    pool.sort(key=lambda r: abs(r["mcap"] - me))
    return [{"t": r["t"], "name": r["name"], "fpe": r["fpe"]} for r in pool[:n]]
