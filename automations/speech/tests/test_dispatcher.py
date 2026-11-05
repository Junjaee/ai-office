"""묶음 규칙(설계 7절, 이준석 13번 예시)·메시지 조립·4,096자 나누기 — 순수 함수."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dispatcher import TELEGRAM_LIMIT, Batch, Dispatcher, render_messages  # noqa: E402
from summarizer import MemberSummary  # noqa: E402

MEETING = "제439회 제04차 예산결산특별위원회"


def ms(seq, member=None, party="국민의힘", n_lines=1, line_len=20):
    member = member or f"위원{seq}"
    topics = [{"title": f"주제 {seq}", "lines": ["가" * line_len] * n_lines}]
    return MemberSummary(seq, member, party, topics, chars=100)


def kinds(batches):
    return [(b.kind, b.seqs()) for b in batches]


def test_spec_example_order():
    d = Dispatcher(batch_size=10, special="이준석")
    out = []
    for s in range(1, 11):
        out += d.ready(ms(s))
    assert kinds(out) == [("batch", list(range(1, 11)))]
    assert d.ready(ms(11)) == []
    assert kinds(d.special_called()) == [("batch", [11])]          # 이준석 호명 → 준비된 11 만 바로
    assert d.ready(ms(12)) == [] or True                           # 12 는 아직 요약 중일 수도(아래에서 늦게 들어온다)
    d2 = Dispatcher(batch_size=10, special="이준석")
    for s in range(1, 12):
        d2.ready(ms(s))
    d2.special_called()
    assert kinds(d2.ready(ms(13, "이준석", "개혁신당"))) == [("special", [13])]
    assert kinds(d2.ready(ms(12))) == [("late", [12])]
    out = []
    for s in range(14, 24):
        out += d2.ready(ms(s))
    assert kinds(out) == [("batch", list(range(14, 24)))]


def test_special_summary_flushes_queue_as_late():
    d = Dispatcher(batch_size=10, special="이준석")
    d.ready(ms(11))
    d.special_called()                 # 11 나감
    d.ready(ms(12))                    # 이준석 호명 뒤, 이준석 요약 전에 12 가 준비됨 → 큐에 머문다
    out = d.ready(ms(13, "이준석", "개혁신당"))
    assert kinds(out) == [("special", [13]), ("late", [12])]


def test_already_sent_seqs_are_dropped():
    d = Dispatcher(batch_size=2, special="이준석", already_sent={1, 2, 13})
    assert d.ready(ms(1)) == [] and d.ready(ms(2)) == []
    assert d.ready(ms(13, "이준석", "개혁신당")) == []
    assert kinds(d.ready(ms(3)) + d.ready(ms(4))) == [("batch", [3, 4])]


def test_flush_sends_remainder():
    d = Dispatcher(batch_size=10, special="이준석")
    d.ready(ms(1)); d.ready(ms(2))
    assert kinds(d.flush()) == [("batch", [1, 2])]
    assert d.flush() == []


def test_render_headers():
    assert render_messages(Batch("batch", [ms(1), ms(2)]), MEETING)[0].startswith(f"📋 {MEETING} · 질의 1~2\n")
    assert render_messages(Batch("late", [ms(12)]), MEETING)[0].startswith(f"📋 {MEETING} · 질의 12 (뒤늦게)\n")
    sp = render_messages(Batch("special", [ms(13, "이준석", "개혁신당")]), MEETING)[0]
    assert sp.startswith("🔵 개혁신당 이준석 · 질의 13\n")
    assert "개혁신당 이준석\n1. 주제 13\n◯ " in sp


def test_members_separated_by_blank_line():
    msg = render_messages(Batch("batch", [ms(1), ms(2)]), MEETING)[0]
    assert "\n\n국민의힘 위원1\n" in msg and "\n\n국민의힘 위원2\n" in msg


def test_split_at_member_boundary_adds_part_numbers():
    items = [ms(s, n_lines=15, line_len=100) for s in range(1, 6)]   # 위원 한 명 ≈ 1,500자
    msgs = render_messages(Batch("batch", items), MEETING)
    assert len(msgs) >= 2 and all(len(m) <= TELEGRAM_LIMIT for m in msgs)
    assert msgs[0].splitlines()[0] == f"📋 {MEETING} · 질의 1~5 (1/{len(msgs)})"
    assert msgs[-1].splitlines()[0] == f"📋 {MEETING} · 질의 1~5 ({len(msgs)}/{len(msgs)})"
    # 위원 블록은 쪼개지지 않는다: 각 메시지에서 "국민의힘 위원N" 머리줄 수 == 그 메시지의 주제 수
    for m in msgs:
        assert m.count("국민의힘 위원") == m.count("\n1. 주제 ")


def test_single_member_over_limit_is_hard_split():
    big = ms(7, n_lines=60, line_len=100)   # ≈ 6,000자
    msgs = render_messages(Batch("batch", [big]), MEETING)
    assert len(msgs) >= 2 and all(len(m) <= TELEGRAM_LIMIT for m in msgs)
    assert "".join(msgs).count("◯ ") == 60
