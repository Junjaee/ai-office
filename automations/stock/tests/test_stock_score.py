"""점수·시장 상태·글 만들기 (순수 함수) 테스트."""
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stock_message as M  # noqa: E402
import stock_score as S  # noqa: E402


def _close(n=260):
    idx = pd.bdate_range("2025-01-01", periods=n)
    spy = pd.Series(np.linspace(100, 130, n), index=idx)
    return pd.DataFrame({"SPY": spy, "^VIX": 14.0 + 0 * spy, "KRW=X": 1380.0 + 0 * spy,
                         "AAA": spy * 0.5, "BBB": spy * 2, "CCC": spy})


def test_market_state_reads_last_day():
    st = S.market_state(_close())
    assert st["spy_above_ma200"] is True
    assert st["vix_bucket"] == "낮음"
    assert st["spy_dd_1y"] == 0.0
    assert st["date"] == _close().index[-1].date()


def test_quarter_logic():
    assert S.quarter_of(date(2026, 10, 1)) == "2026-Q4"
    assert S.is_new_quarter(None, date(2026, 10, 1))
    assert S.is_new_quarter("2026-Q3", date(2026, 10, 1))
    assert not S.is_new_quarter("2026-Q4", date(2026, 11, 15))


def _members():
    return pd.DataFrame({"ticker": ["AAA", "BBB", "CCC"], "name": ["A사", "B사", "C사"],
                         "sector": ["IT", "금융", "IT"], "cik": [1, 2, 3]})


def _fund(cheap, rich):
    base = dict(rev=100.0, ni=10.0, ocf=12.0, equity=50.0, div=2.0, buyback=3.0, period_end=date(2026, 6, 30))
    return {"AAA": dict(base, shares=cheap), "BBB": dict(base, shares=rich), "CCC": dict(base, shares=(cheap + rich) / 2)}


def test_score_prefers_cheaper_same_fundamentals():
    close = _close()
    last = close.iloc[-1]
    # 같은 재무값이면 시총이 작은 쪽(비율이 큰 쪽)이 위
    t = S.score_table(_members(), last, _fund(cheap=1.0, rich=10.0))
    assert list(t["ticker"])[0] == "AAA" and list(t["ticker"])[-1] == "BBB"
    assert t["점수"].iloc[0] > t["점수"].iloc[-1]
    top = S.top_n(t, 2)
    assert list(top["ticker"]) == ["AAA", "CCC"]
    assert abs(top["비중"].sum() - 1) < 1e-9


def test_score_drops_missing_core_values():
    f = _fund(1.0, 10.0)
    f["BBB"]["ni"] = float("nan")
    t = S.score_table(_members(), _close().iloc[-1], f)
    assert "BBB" not in set(t["ticker"])


def test_diff_and_messages():
    new, gone = S.diff_picks(["A", "B"], ["B", "C"])
    assert new == ["A"] and gone == ["C"]
    st = S.market_state(_close())
    txt = M.status_text(st, observe=True)
    assert txt.startswith("[주식 신호]") and "관찰 중" in txt and "200일선 위" in txt
    t = S.score_table(_members(), _close().iloc[-1], _fund(1.0, 10.0))
    top = S.top_n(t, 2)
    s2 = M.screen_text(top, "2026-Q4", "equal", True, ["AAA"], [], len(t), st["date"])
    assert "상위 2" in s2 and "AAA" in s2 and "★새" in s2 and M.DISCLAIMER in s2
    lines = M.public_lines(st, 3, True, "2026-Q4", 1, 0)
    assert lines[0] == f"기준일 {st['date'].isoformat()}"
    assert all("AAA" not in ln for ln in lines)       # 공개 줄에 종목명 없음
    back = M.parse_state_lines(lines)
    assert back["date"] == st["date"].isoformat() and back["quarter"] == "2026-Q4"
