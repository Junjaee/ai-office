"""kis_universe — 네트워크 없이 시총 범위·두 층·돌려 가며 조회 계획을 검사한다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kis_universe as ku  # noqa: E402

EOK = 1e8


def _row(code, mcap_eok, amount_eok, price=1000, halted=False):
    return {"code": code, "name": "n" + code, "market": "KOSDAQ", "mcap": mcap_eok * EOK, "amount": amount_eok * EOK, "price": price, "halted": halted}


def test_build_universe_filters_and_tiers():
    listing = [
        _row("000010", 10_000, 500),        # 시총 너무 큼 → 제외
        _row("000020", 100, 50),            # 시총 너무 작음 → 제외
        _row("000030", 1_000, 30),          # 범위 안, 거래대금 2위
        _row("000040", 2_000, 80),          # 범위 안, 거래대금 1위
        _row("000050", 500, 5),             # 범위 안, 3위
        _row("000060", 800, 1, price=300),  # 주가 하한
        _row("000070", 800, 900, halted=True),  # 거래정지
    ]
    uni = ku.build_universe(listing, watchlist=["005930"], candidates=["000050", "bad"], tier_a_size=3, cap_min_eok=300, cap_max_eok=5000)
    # 관심·후보 먼저(시총 무관), 그다음 범위 안 거래대금 상위로 채움
    assert uni.tier_a == ["005930", "000050", "000040"]
    assert uni.tier_b == ["000030"]
    assert uni.excluded["시총 범위 밖"] == 2 and uni.excluded["거래정지"] == 1 and uni.excluded["주가 하한"] == 1
    assert uni.excluded["범위 안 종목"] == 3


def test_sweep_plan_rotates_tier_b():
    uni = ku.Universe(tier_a=["A1", "A2"], tier_b=[f"B{i}" for i in range(5)])
    # 예산 4건(6초/1.5초) → A층 2 + B층 2, 바퀴마다 B층이 이어짐
    assert uni.sweep_plan(6, 1.5, 0) == ["A1", "A2", "B0", "B1"]
    assert uni.sweep_plan(6, 1.5, 1) == ["A1", "A2", "B2", "B3"]
    assert uni.sweep_plan(6, 1.5, 2) == ["A1", "A2", "B4", "B0"]
    # 예산이 A층보다 작아도 A층은 전부
    assert uni.sweep_plan(1, 1.5, 0) == ["A1", "A2"]
    # B층 없으면 A층만
    assert ku.Universe(["A1"], []).sweep_plan(60, 1.5, 3) == ["A1"]


def test_load_lines_filters_codes(tmp_path):
    p = tmp_path / "c.txt"; p.write_text("005930\n# 주석\nabc\n000660 \n", encoding="utf-8")
    assert ku.load_lines(p) == ["005930", "000660"]
    assert ku.load_lines(None) == [] and ku.load_lines(tmp_path / "없음") == []
