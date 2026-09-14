"""댓글 → DM(insta_dm) — 키워드 판정, 7일 창, 중복 방지, 권한 오류 안내. HTTP 는 가짜 호출로."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import insta_dm as dm  # noqa: E402

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def fake_api(comments_by_media, fail=None):
    calls = []

    def call(method, path, token, params=None, body=None):
        calls.append((method, path, params, body))
        if fail and fail(method, path):
            raise dm.ApiError(400, "(#10) Application does not have permission for this action", 10)
        if method == "GET" and path.endswith("/comments"):
            return {"data": comments_by_media.get(path.split("/")[0], [])}
        return {"id": "ok"}

    call.calls = calls
    return call


def test_matches_keyword_or_any():
    assert dm.matches("프롬프트 주세요!", "프롬프트") and dm.matches("프 롬 프 트", "프롬프트") and not dm.matches("좋아요", "프롬프트")
    assert dm.matches("아무거나", "") and not dm.matches("   ", "")


def test_run_sends_once_per_comment_and_skips_old_posts_and_own_comments():
    posted = [
        {"media_id": "m1", "hook": "글1", "dm_keyword": "프롬프트", "dm_text": "여기 프롬프트입니다", "date": "2026-09-11"},
        {"media_id": "m2", "hook": "글2", "dm_keyword": "", "dm_text": "아무 댓글에나", "date": "2026-09-01"},   # 11일 전 → 제외
        {"media_id": "m3", "hook": "글3", "dm_keyword": "", "dm_text": "", "date": "2026-09-12"},             # DM 글 없음 → 제외
    ]
    comments = {"m1": [
        {"id": "c1", "text": "프롬프트 부탁드려요", "username": "fan1"},
        {"id": "c2", "text": "멋져요", "username": "fan2"},
        {"id": "c3", "text": "프롬프트!", "username": "aitips.kr"},        # 우리 댓글
        {"id": "c4", "text": "프롬프트요", "username": "fan4"},            # 이미 보냄
    ]}
    call = fake_api(comments)
    new, s = dm.run(posted=posted, log=[{"comment_id": "c4"}], token="t", user_id="u", own_username="aitips.kr", now=NOW, call=call, progress=lambda m: None)
    assert s["posts"] == 1 and s["sent"] == 1 and s["failed"] == 0
    assert [e["comment_id"] for e in new] == ["c1"] and new[0]["status"] == "sent"
    posts = [c for c in call.calls if c[0] == "POST"]
    assert posts[0][1] == "u/messages" and posts[0][3] == {"recipient": {"comment_id": "c1"}, "message": {"text": "여기 프롬프트입니다"}}
    assert posts[1][1] == "c1/replies" and "DM" in posts[1][2]["message"]


def test_permission_error_stops_with_hint():
    posted = [{"media_id": "m1", "hook": "글1", "dm_keyword": "", "dm_text": "x", "date": NOW.strftime("%Y-%m-%d")}]
    msgs = []
    call = fake_api({"m1": [{"id": "c1", "text": "hi", "username": "a"}]}, fail=lambda m, p: p.endswith("/messages"))
    new, s = dm.run(posted=posted, log=[], token="t", user_id="u", own_username="me", now=NOW, call=call, progress=msgs.append)
    assert s["permission"] and s["failed"] == 1 and new[0]["status"] == "failed"
    assert any("instagram_business_manage_messages" in m for m in msgs)


def test_window_uses_posted_at_when_present():
    posted = [{"media_id": "m1", "hook": "x", "dm_keyword": "", "dm_text": "t", "date": "2026-09-01", "posted_at": (NOW - timedelta(days=2)).isoformat()}]
    call = fake_api({"m1": [{"id": "c9", "text": "yo", "username": "b"}]})
    new, s = dm.run(posted=posted, log=[], token="t", user_id="u", own_username="me", now=NOW, call=call, progress=lambda m: None)
    assert s["sent"] == 1


def test_resolve_media_ids_fills_blank_ids_by_permalink_once():
    """손으로 적은 게시 기록(게시물 번호 없음)도 주소로 번호를 찾아 DM 대상이 된다. 채울 게 없으면 호출하지 않는다."""
    calls = []

    def call(method, path, token, params=None, body=None):
        calls.append((method, path, params))
        return {"data": [{"id": "111", "permalink": "https://www.instagram.com/p/AAA/"},
                         {"id": "222", "permalink": "https://www.instagram.com/reel/CCC/"}]}

    iso = NOW.isoformat()
    posted = [{"permalink": "https://www.instagram.com/p/AAA/", "media_id": "", "dm_text": "x", "posted_at": iso},
              {"permalink": "https://www.instagram.com/p/BBB/", "media_id": "m9", "dm_text": "y", "posted_at": iso},
              {"permalink": "https://www.instagram.com/reel/CCC/", "media_id": "", "dm_text": "", "posted_at": iso},        # DM 글 아님
              {"permalink": "https://www.instagram.com/p/DDD/", "media_id": "", "dm_text": "z", "date": "2026-08-01"}]     # 7일 지남
    assert dm.resolve_media_ids(posted, "t", "u", NOW, call=call, progress=lambda m: None) == 1
    assert posted[0]["media_id"] == "111" and posted[2]["media_id"] == "" and posted[3]["media_id"] == ""
    assert calls == [("GET", "u/media", {"fields": "id,permalink", "limit": 50})]
    assert dm.resolve_media_ids(posted, "t", "u", NOW, call=call, progress=lambda m: None) == 0 and len(calls) == 1
