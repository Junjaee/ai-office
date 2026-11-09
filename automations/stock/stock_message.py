"""텔레그램 글과 공개용 요약 (순수 함수). 종목명은 텔레그램에만, 공개 상태 파일에는 건수만."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

DISCLAIMER = "규칙의 계산 결과이며 투자 권유가 아닙니다. 검증에서 지수와 같은 수준이었고 우위는 확인되지 않았습니다(docs/stock/13)."


def _pct(x: float, digits: int = 1) -> str:
    return "?" if not np.isfinite(x) else f"{x * 100:+.{digits}f}%"


def status_text(state: dict, observe: bool, screen_note: str = "") -> str:
    d: date = state["date"]
    head = f"[주식 신호] 미국 {d.month}/{d.day}({'월화수목금토일'[d.weekday()]}) 종가 기준"
    if observe:
        head += " · 관찰 중"
    ma = state.get("spy_above_ma200")
    ma_txt = "위" if ma else ("아래" if ma is not None else "?")
    lines = [
        head,
        f"SPY {state['spy']:.0f} ({_pct(state['spy_chg'])}) · 200일선 {ma_txt} ({_pct(state['spy_vs_ma200'])}) · 1년 고점 대비 {_pct(state['spy_dd_1y'])}",
        f"VIX {state['vix']:.1f} ({state['vix_bucket']}) · 환율 {state['krw']:,.0f}원 ({_pct(state['krw_chg'])})",
    ]
    if screen_note:
        lines.append(screen_note)
    return "\n".join(lines)


def screen_text(picks: pd.DataFrame, quarter: str, weight: str, observe: bool,
                new: list[str], gone: list[str], n_cand: int, asof: date) -> str:
    w = "동일가중" if weight == "equal" else "역변동성 가중"
    head = f"[분기 종목] {quarter} · 가치+주주환원 상위 {len(picks)} · {w}"
    if observe:
        head += " · 관찰 중 — 실제 주문 아님"
    lines = [head, f"후보 {n_cand}종목 · 미국 {asof.month}/{asof.day} 종가 · 최근 공시 재무값 기준", ""]
    for i, r in enumerate(picks.to_dict("records"), 1):
        mark = " ★새" if r["ticker"] in new else ""
        lines.append(f"{i:2d}. {r['ticker']:6s} {str(r['name'])[:22]}{mark}")
        lines.append(f"     점수 {r['점수']:+.2f} · E/P {_pct(r.get('E/P', np.nan))}"
                     f" · 환원 {_pct(r.get('주주환원', np.nan))} · 비중 {r['비중'] * 100:.1f}%")
    lines.append("")
    lines.append(f"새로 들어옴 {len(new)} · 빠짐 {len(gone)}" + (f" ({', '.join(gone)})" if gone else ""))
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def public_lines(state: dict, n_cand: int, screened: bool, quarter: str | None, n_new: int,
                 n_fail: int) -> list[str]:
    """상태 파일·실행 기록에 남길 줄 — 날짜·건수만. 종목명 없음."""
    d: date = state["date"]
    out = [f"기준일 {d.isoformat()}"]
    ma = state.get("spy_above_ma200")
    out.append(f"[시장] SPY 200일선 {'위' if ma else '아래'} · VIX {state['vix']:.1f} · 시세 실패 {n_fail}건")
    if screened and quarter:
        out.append(f"[분기] {quarter} 후보 {n_cand} · 상위 20 · 새 종목 {n_new}")
    return out


def parse_state_lines(lines: list[str]) -> dict:
    """지난 실행의 상태 파일 log_lines 에서 기준일과 마지막 분기 알림을 읽는다."""
    out: dict = {"date": None, "quarter": None}
    for ln in lines or []:
        if ln.startswith("기준일 "):
            out["date"] = ln.split(" ", 1)[1].strip()
        if ln.startswith("[분기] "):
            out["quarter"] = ln.split(" ")[1].strip()
    return out
