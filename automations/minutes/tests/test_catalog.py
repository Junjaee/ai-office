from catalog import iter_entries
from record_site import Committee, Meeting, Session


class FakeSite:
    """대수 22, 상임위 2개(AS, AF)·본회의·국감을 흉내 낸다."""

    def committees(self, th, cls):
        return {
            1: [Committee("", "국회본회의")],
            2: [Committee("AS", "재정경제기획위원회"), Committee("AF", "과학기술정보방송통신위원회")],
            4: [Committee("G1", "예산결산특별위원회")],
            5: [Committee("AG", "과학기술정보방송통신위원회")],
        }.get(cls, [])

    def sessions(self, th, cls, code):
        if cls == 5:
            return [Session("2025", "2025"), Session("2024", "2024"), Session("2023", "2023")]
        return [Session("439", "제439회"), Session("438", "제438회"), Session("437", "제437회")]

    def meetings(self, th, cls, code, key):
        return [Meeting(int(f"{cls}{key[-2:]}01"), f"{code or 'PL'} {key} 제1차", key == "439", True)]


def test_iter_entries_all_walks_every_class_and_session():
    entries = list(iter_entries(FakeSite(), th=22, classes=[1, 2, 4, 5]))
    # 본회의 3 + 상임위 2*3 + 예결위 3 + 국감 3 = 15
    assert len(entries) == 15
    e = next(x for x in entries if x.committee == "재정경제기획위원회" and x.sess == "438")
    assert (e.th, e.cls, e.title, e.temp, e.has_pdf) == (22, 2, "AS 438 제1차", False, True)


def test_iter_entries_recent_limits_sessions():
    entries = list(iter_entries(FakeSite(), th=22, classes=[2, 5], recent=2))
    sess = {(x.committee, x.sess) for x in entries}
    assert ("재정경제기획위원회", "437") not in sess
    assert ("재정경제기획위원회", "438") in sess
    assert ("과학기술정보방송통신위원회", "2023") not in sess
    assert ("과학기술정보방송통신위원회", "2024") in sess


def test_iter_entries_reports_progress(capsys):
    seen = []
    list(iter_entries(FakeSite(), th=22, classes=[1], progress=seen.append))
    assert any("국회본회의" in s for s in seen)


def test_iter_temp_recheck_groups_by_committee_and_session():
    from catalog import iter_temp_recheck

    class CountingSite(FakeSite):
        def __init__(self):
            self.meeting_calls = []

        def meetings(self, th, cls, code, key):
            self.meeting_calls.append((cls, code, key))
            return super().meetings(th, cls, code, key)

    site = CountingSite()
    pending = [
        {"th": 22, "cls": 2, "committee": "재정경제기획위원회", "sess": "438"},
        {"th": 22, "cls": 2, "committee": "재정경제기획위원회", "sess": "438"},   # 같은 회기 중복
        {"th": 22, "cls": 2, "committee": "재정경제기획위원회", "sess": "437"},
        {"th": 22, "cls": 1, "committee": "국회본회의", "sess": "439"},
        {"th": 22, "cls": 2, "committee": "없는위원회", "sess": "438"},          # 코드 없음 → 건너뜀
        {"th": 22, "cls": 2, "committee": "재정경제기획위원회", "sess": ""},     # 회기 없음 → 무시
    ]
    entries = list(iter_temp_recheck(site, 22, pending))
    assert sorted(site.meeting_calls) == [(1, "", "439"), (2, "AS", "437"), (2, "AS", "438")]
    assert {(e.cls, e.committee, e.sess) for e in entries} == {
        (1, "국회본회의", "439"), (2, "재정경제기획위원회", "437"), (2, "재정경제기획위원회", "438")}
    assert all(e.temp in (True, False) for e in entries)
