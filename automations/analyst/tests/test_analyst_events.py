import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analyst_events import classify  # noqa: E402

F = [
    {"form": "8-K", "date": "2026-09-30", "items": "2.02,9.01"},
    {"form": "8-K", "date": "2026-09-30", "items": "2.02"},          # 같은 날 같은 종류 → 하나
    {"form": "8-K/A", "date": "2026-09-25", "items": "5.02, 1.01"},
    {"form": "10-Q", "date": "2026-09-29", "items": ""},              # 8-K 가 아님
    {"form": "8-K", "date": "2026-09-01", "items": "2.01"},           # 14일 밖
    {"form": "8-K", "date": "2026-10-09", "items": "2.01"},           # 기준일 뒤
    {"form": "8-K", "date": "bad", "items": "2.01"},
]


def test_classify_keeps_recent_8k_items_newest_first():
    assert classify(F, "2026-10-02") == [
        {"date": "2026-09-30", "kind": "실적 발표"},
        {"date": "2026-09-25", "kind": "임원 교체"},
        {"date": "2026-09-25", "kind": "주요 계약"},
    ]


def test_classify_ignores_unknown_items_and_bad_rows():
    assert classify([{"form": "8-K", "date": "2026-10-01", "items": "7.01,9.01"}, {}, {"form": None}], "2026-10-02") == []


def test_classify_window_edges_are_inclusive():
    def f(d):
        return [{"form": "8-K", "date": d, "items": "2.02"}]
    assert classify(f("2026-10-02"), "2026-10-02") and classify(f("2026-09-18"), "2026-10-02")   # 기준일·14일 전 포함
    assert classify(f("2026-09-17"), "2026-10-02") == []                                          # 15일 전은 제외
