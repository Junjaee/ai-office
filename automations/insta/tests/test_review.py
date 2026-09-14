"""주제 검토·예약 파일(insta_review) — 간격 계산, 예약, 만들 시각 판정, 상태 표시."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import insta_review as review  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 12, 9, 17, tzinfo=KST)


def cands(n):
    return [{"key": f"https://x.test/{i}", "title": f"후보 {i}", "link": f"https://x.test/{i}", "source": "T",
             "summary": "", "reason": "r", "angle": "a"} for i in range(n)]


def test_schedule_spreads_24h_over_n_and_rounds_to_hour():
    times = review.schedule_times(3, NOW)                       # 24÷3 = 8시간 간격
    assert times[0] == NOW
    assert [t.strftime("%H:%M") for t in times[1:]] == ["18:00", "02:00"]   # 17:17→18:00, 01:17→02:00 로 올림
    assert review.schedule_times(1, NOW) == [NOW]
    five = review.schedule_times(5, NOW)                         # 4.8시간 간격 → 14:05→15:00, 18:53→19:00 …
    assert [t.strftime("%H:%M") for t in five] == ["09:17", "15:00", "19:00", "00:00", "05:00"]


def test_slots_assign_next_free_fixed_times_and_skip_taken():
    # 09:17 에 4개 → 12:30, 18:30, 다음 날 07:30, 12:30
    four = review.slot_times(4, NOW)
    assert [t.strftime("%d %H:%M") for t in four] == ["12 12:30", "12 18:30", "13 07:30", "13 12:30"]
    # 12:30 이 이미 예약돼 있으면 건너뛴다 / 07:28 이면 07:30 은 유예(5분) 때문에 건너뛴다
    taken = [datetime(2026, 9, 12, 12, 30, tzinfo=KST)]
    assert [t.strftime("%H:%M") for t in review.slot_times(2, NOW, taken=taken)] == ["18:30", "07:30"]
    assert review.slot_times(1, datetime(2026, 9, 12, 7, 28, tzinfo=KST))[0].strftime("%H:%M") == "12:30"
    data = review.set_candidates({"queue": []}, cands(3), now=NOW)
    ids = [c["id"] for c in data["candidates"]]
    data, a = review.enqueue(data, ids[:2], now=NOW, slots=review.DEFAULT_SLOTS)
    assert [x["due"][11:16] for x in a] == ["12:30", "18:30"]
    data, b = review.enqueue(data, ids[2:], now=NOW, slots=review.DEFAULT_SLOTS)
    assert b[0]["due"].startswith("2026-09-13T07:30"), "이미 찬 칸은 건너뛰고 다음 날 첫 칸"
    # 시간대 창 판정: 12:30 창도 자동 선택 대상 (전 시간대 자동, 2026-09-14)
    assert review.in_slot_window(datetime(2026, 9, 12, 12, 35, tzinfo=KST)) == "12:30" and review.in_slot_window(datetime(2026, 9, 12, 10, 0, tzinfo=KST)) == ""
    busy = review.set_candidates({"queue": []}, cands(2), now=NOW)
    busy, first = review.enqueue(busy, [busy["candidates"][0]["id"]], now=datetime(2026, 9, 12, 12, 0, tzinfo=KST), slots=review.DEFAULT_SLOTS)  # 12:30 예약
    assert review.auto_pick(busy, exclude_keys=set(), now=datetime(2026, 9, 12, 12, 33, tzinfo=KST), slots=review.DEFAULT_SLOTS)[1] == [], "그 칸이 차 있으면 자동 선택 안 함"
    # 07:30 창 판정과 자동 선택(첫 개는 바로)
    assert review.is_first_slot(datetime(2026, 9, 12, 7, 31, tzinfo=KST)) and not review.is_first_slot(datetime(2026, 9, 12, 8, 30, tzinfo=KST))
    fresh = review.set_candidates({"queue": []}, cands(2), now=NOW)
    at = datetime(2026, 9, 12, 7, 32, tzinfo=KST)
    fresh, auto = review.auto_pick(fresh, exclude_keys=set(), now=at, slots=review.DEFAULT_SLOTS)
    assert len(auto) == 1 and auto[0]["due"] == at.isoformat(timespec="seconds")


def test_daily_cap_spreads_over_days_and_starts_after_existing_queue():
    five = review.schedule_times(5, NOW, max_per_day=3)                    # 8시간 간격으로 5개 → 이틀에 걸침
    assert [t.strftime("%d %H:%M") for t in five] == ["12 09:17", "12 18:00", "13 02:00", "13 10:00", "13 18:00"]
    data = review.set_candidates({"queue": []}, cands(4), now=NOW)
    ids = [c["id"] for c in data["candidates"]]
    data, a = review.enqueue(data, ids[:2], now=NOW, max_per_day=3)          # 2개 → 12시간 간격: 09:17, 22:00
    assert data["interval_hours"] == 12.0 and [x["due"][11:16] for x in a] == ["09:17", "22:00"]
    data, b = review.enqueue(data, ids[2:], now=NOW + timedelta(minutes=10), max_per_day=3)   # 이미 예약 있음 → 22:00 + 8h = 06:00 부터
    assert [x["due"][8:16] for x in b] == ["13T06:00", "13T18:00"], "몰아 올리지 않고 마지막 예약 뒤에 이어 붙는다"


def test_enqueue_skips_unknown_and_already_queued_and_marks_due():
    data = review.set_candidates({"queue": []}, cands(4), now=NOW)
    ids = [c["id"] for c in data["candidates"]]
    data, added = review.enqueue(data, [ids[0], "nope", ids[2], ids[0]], now=NOW)
    assert [a["title"] for a in added] == ["후보 0", "후보 2"] and data["interval_hours"] == 12
    assert [q["status"] for q in data["queue"]] == ["queued", "queued"]
    assert review.active_keys(data) == {"https://x.test/0", "https://x.test/2"}
    # 지금 만들 것은 첫 개뿐
    assert [q["title"] for q in review.due_items(data, NOW)] == ["후보 0"]
    assert [q["title"] for q in review.due_items(data, NOW + timedelta(hours=13))] == ["후보 0", "후보 2"]
    # 다시 고르면 이미 예약된 것은 빠진다
    data, again = review.enqueue(data, [ids[0], ids[1]], now=NOW)
    assert [a["title"] for a in again] == ["후보 1"]


def test_mark_and_new_day_keeps_active_queue_only():
    data = review.set_candidates({"queue": []}, cands(2), now=NOW)
    ids = [c["id"] for c in data["candidates"]]
    data, _ = review.enqueue(data, ids, now=NOW)
    data = review.mark(data, ids[0], "making", now=NOW)
    data = review.mark(data, ids[0], "done", now=NOW, permalink="https://instagram.com/p/x/")
    assert data["queue"][0]["status"] == "done" and data["queue"][0]["permalink"].endswith("/x/")
    assert "게시 1건" in review.summarize(data) and "예약 1건" in review.summarize(data)
    # 3일 뒤 새 후보: 끝난 항목은 지워지고 예약된 항목은 남는다
    later = review.set_candidates(data, cands(1), now=NOW + timedelta(days=3))
    assert [q["status"] for q in later["queue"]] == ["queued"] and later["count"] == 1


def test_auto_pick_takes_first_candidate_only_when_nothing_is_queued():
    data = review.set_candidates({"queue": []}, cands(3), now=NOW)
    # 이미 올린 것(0번)은 건너뛰고 1번을 지금 예약
    data, added = review.auto_pick(data, exclude_keys={"https://x.test/0"}, now=NOW)
    assert [a["title"] for a in added] == ["후보 1"] and added[0]["due"] == NOW.isoformat(timespec="seconds")
    # 예약이 있으면 아무것도 안 한다
    again, none = review.auto_pick(data, exclude_keys=set(), now=NOW + timedelta(hours=1))
    assert none == [] and again == data
    # 후보가 이틀 넘게 묵었으면 안 한다
    stale = review.set_candidates({"queue": []}, cands(1), now=NOW)
    assert review.auto_pick(stale, exclude_keys=set(), now=NOW + timedelta(days=3))[1] == []
    assert review.auto_pick(stale, exclude_keys=set(), now=NOW, n=0)[1] == []


def test_apply_edits_cancels_and_reschedules_queued_only():
    data = review.set_candidates({"queue": []}, cands(3), now=NOW)
    ids = [c["id"] for c in data["candidates"]]
    data, _ = review.enqueue(data, ids, now=NOW)                    # 09:17, 18:00, 02:00
    data = review.mark(data, ids[0], "done", now=NOW)
    edits = review.parse_edits(f"{ids[0]}=cancel,{ids[1]}=07:30,{ids[2]}=cancel,zzz=cancel,{ids[1]}=bad")
    assert len(edits) == 4, "id 가 8자가 아닌 조각은 버린다"
    data, changed = review.apply_edits(data, edits, now=NOW)
    assert data["queue"][0]["status"] == "done", "끝난 항목은 못 건드린다"
    assert data["queue"][2]["status"] == "cancelled"
    assert data["queue"][1]["due"].startswith("2026-09-13T07:30"), "07:30 은 이미 지났으니 내일"
    assert len(changed) == 2 and changed[0].startswith("09/13 07:30")
    assert review.resolve_time("2026-09-20T10:00", NOW).isoformat().startswith("2026-09-20T10:00:00+09:00")
    assert review.resolve_time("25:00", NOW) is None


def test_has_due_reads_file(tmp_path):
    path = tmp_path / "public" / "review" / "side" / "insta_aitips.json"
    assert review.has_due(path) is False
    data = review.set_candidates({"queue": []}, cands(1), now=NOW)
    data, _ = review.enqueue(data, [data["candidates"][0]["id"]], now=NOW)
    review.save(path, data)
    assert review.has_due(path, NOW) is True and review.has_due(path, NOW - timedelta(hours=1)) is False


def test_similar_titles_are_treated_as_repeats():
    assert review.is_repeat({"title_ko": "챗GPT로 내 개인정보 지우기", "title": "x"}, ["챗GPT 프롬프트 3개로 내 정보 지우기 🧹"])
    assert not review.is_repeat({"title_ko": "제미나이 윈도우 앱 출시", "title": "Hello Windows"}, ["챗GPT 프롬프트 3개로 내 정보 지우기 🧹"])
    data = review.set_candidates({"queue": []}, [{"key": "k1", "title": "Hungry", "title_ko": "챗GPT로 내 정보 지우기", "link": "l", "source": "s"},
                                                {"key": "k2", "title": "Win", "title_ko": "윈도우 제미나이 앱", "link": "l2", "source": "s"}], now=NOW)
    _, added = review.auto_pick(data, exclude_keys=set(), now=NOW, slots=review.DEFAULT_SLOTS, posted_titles=["챗GPT 프롬프트 3개로 내 정보 지우기"])
    assert [a["title"] for a in added] == ["Win"], "비슷한 주제는 건너뛰고 다음 후보"


def test_rate_limit_detection():
    import run_insta
    assert run_insta.is_rate_limited("RuntimeError: Instagram 오류 403: Application request limit reached (code 4)")
    assert not run_insta.is_rate_limited("RuntimeError: Instagram 오류 400: Invalid parameter (code 100)")
