"""insta 자동화 — 오프라인으로 검사할 수 있는 부분: 소재 걸러내기, JSON 추출·스키마, 기사 검사·검수 루프, 카드 계획·슬라이드, 사진 후보, 게시 흐름(가짜 API)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))

import insta_cards as cards  # noqa: E402
import insta_publisher as pub  # noqa: E402
import insta_research as research  # noqa: E402
import insta_sources as sources  # noqa: E402
import insta_watch as watch  # noqa: E402
import insta_writer as writer  # noqa: E402
from insta_llm import LLM, LLMError, extract_json  # noqa: E402

NOW = datetime(2026, 9, 11, 9, 0, tzinfo=timezone.utc)


def cand(title, hours_ago, link="https://x.test/a", summary=""):
    return sources.Candidate(key=sources.normalize_key(link), title=title, link=link, source="T",
                             published=NOW - timedelta(hours=hours_ago), summary=summary)


def test_collect_filters_age_dupes_and_marks_signals(monkeypatch):
    items = [cand("ChatGPT 새 기능 프롬프트", 5, "https://x.test/a?utm=1"),
             cand("오래된 글", 200, "https://x.test/old"),
             cand("이미 올린 글", 2, "https://x.test/posted"),
             cand("중복", 3, "https://x.test/a")]
    monkeypatch.setattr(sources, "fetch_source", lambda name, **kw: items)
    found, failed = sources.collect(["openai_news"], max_age_hours=72, signals=["프롬프트", "free"],
                                    exclude_keys={"https://x.test/posted"}, now=NOW, progress=lambda m: None)
    assert failed == []
    assert [c.title for c in found] == ["ChatGPT 새 기능 프롬프트"]
    assert found[0].signals == ["프롬프트"]


def test_collect_keeps_going_when_a_source_fails(monkeypatch):
    def fake(name, **kw):
        if name == "bad":
            raise RuntimeError("down")
        return [cand("ok", 1)]
    monkeypatch.setattr(sources, "fetch_source", fake)
    sources.SOURCES["bad"] = {"kind": "rss", "url": "x", "label": "bad"}
    found, failed = sources.collect(["bad", "openai_news"], max_age_hours=72, signals=[], exclude_keys=set(),
                                    now=NOW, progress=lambda m: None)
    assert len(found) == 1 and len(failed) == 1


def test_extract_json_handles_fences_and_prose():
    assert extract_json('설명입니다 ```json\n{"a": 1}\n``` 끝') == {"a": 1}
    assert extract_json('앞말 {"b": [1, 2]} 뒷말') == {"b": [1, 2]}
    with pytest.raises(ValueError):
        extract_json("JSON 없음")


def test_llm_falls_through_providers_and_retries_schema(monkeypatch):
    llm = LLM(["claude_cli", "gemini"])
    monkeypatch.setattr(llm, "_available", lambda name: True)
    calls = []

    def bad(system, user):
        calls.append("claude")
        raise RuntimeError("Not logged in")

    answers = iter(['{"x": "no"}', '{"x": 3}'])

    def gem(system, user):
        calls.append("gemini")
        return next(answers)

    monkeypatch.setattr(llm, "_call_claude_cli", bad)
    monkeypatch.setattr(llm, "_call_gemini", gem)
    schema = {"type": "object", "required": ["x"], "properties": {"x": {"type": "integer"}}}
    assert llm.json(system="s", user="u", schema=schema) == {"x": 3}
    assert calls == ["claude", "gemini", "gemini"]
    assert llm.last_provider == "gemini"


def test_llm_raises_when_all_fail(monkeypatch):
    llm = LLM(["gemini"])
    monkeypatch.setattr(llm, "_available", lambda name: False)
    with pytest.raises(LLMError):
        llm.json(system="s", user="u")


def sample_article():
    para = "구글이 9월 10일 윈도우용 제미나이(Gemini) 앱을 내놨어요. Alt+Space 를 누르면 하던 화면 위에 바로 떠요. 브라우저 탭을 찾지 않아도 돼요. 무료 계정으로도 쓸 수 있어요."
    return {"title": "구글, 윈도우용 제미나이 앱 출시", "subtitle": "Alt+Space 한 번이면 화면 위에 AI",
            "paragraphs": [{"heading": f"소주제 {i}", "text": para} for i in range(6)],
            "caption": "제목 반복\n\n핵심 요약 문장을 조금 길게 써서 길이 조건을 채웁니다. 실제로는 삼백 자 안팎으로 씁니다.\n\n저장해 두세요.",
            "hashtags": ["AI활용", "#챗GPT", "#제미나이"], "alt_text": "카드뉴스",
            "sources": ["https://blog.google/x"], "claims": [{"text": "9월 10일 출시", "source": "https://blog.google/x"}]}


def profile(**over):
    d = {"name": "t", "audience": "a", "tone": "t", "format": "news", "paragraphs": 6,
         "must_include": [], "banned": ["게임체인저"], "cta": "저장", "hashtags_base": ["#a"], "sources": [],
         "source_signals": [], "template": "dark_code", "judge_weights": {"readability": 3}, "pass_score": 38}
    d.update(over)
    return writer.Profile.from_dict(d)


def test_local_checks_flag_banned_missing_sources_paragraph_length_and_fix_hashtags():
    p = profile()
    art = sample_article()
    assert writer.local_checks(p, art) == []
    assert art["hashtags"][0] == "#AI활용"
    art["paragraphs"][0]["text"] = "게임체인저"
    art["claims"][0]["source"] = "출처 없음"
    problems = writer.local_checks(p, art)
    assert any("금지" in x for x in problems) and any("URL" in x for x in problems) and any("짧음" in x for x in problems)


def test_generate_article_revises_until_editor_passes():
    p = profile()
    seq = iter([sample_article(), {"scores": {}, "total": 20, "verdict": "revise", "feedback": "3번 문단이 추상적"},
                sample_article(), {"scores": {}, "total": 45, "verdict": "pass", "feedback": ""}])
    prompts = []

    class Fake:
        last_provider = "fake"

        def json(self, *, system, user, schema=None):
            prompts.append(user)
            return next(seq)

    art, verdict = writer.generate_article(Fake(), p, "refs", {"title": "t", "source": "s", "link": "l"}, "관련 글",
                                           progress=lambda m: None)
    assert verdict["verdict"] == "pass"
    assert "3번 문단이 추상적" in prompts[2], "2차 기사 요청에 검수 지적이 붙는다"
    assert "관련 글" in prompts[0], "조사 결과가 글쓰기 프롬프트에 들어간다"


def test_plan_cards_uses_paragraphs_verbatim_and_maps_images():
    p = profile()
    images = [{"id": 1, "url": "https://img/1.jpg", "alt": "앱 화면", "source_url": "https://blog.google/x",
               "source_title": "구글 블로그", "kind": "official"}]
    bad = {"cover": {"title": "구글, 윈도우용\\n제미나이 앱 출시", "sub": "s", "image_id": 0},
           "cards": [{"image_id": 9 if i == 0 else 0} for i in range(6)], "cta": "저장"}
    good = json.loads(json.dumps(bad)); good["cards"][0]["image_id"] = 1
    seq = iter([bad, good])

    class Fake:
        last_provider = "fake"

        def json(self, *, system, user, schema=None):
            return next(seq)

    art = sample_article()
    art["paragraphs"][0]["heading"] = "소주제\n둘째 줄"
    plan = writer.plan_cards(Fake(), p, art, images, progress=lambda m: None)
    assert plan["cover"]["image"]["url"] == "https://img/1.jpg", "표지: 고른 사진 없으면 공식 사진이라도"
    assert plan["cards"][0]["image"] is None and plan["cards"][1]["image"] is None, "표지에 쓴 사진은 카드에 다시 안 쓴다"
    assert plan["cards"][0]["title"] == "소주제 둘째 줄", "소제목은 한 줄"
    assert plan["cards"][0]["lines"][0].startswith("구글이 9월 10일") and len(plan["cards"][0]["lines"]) == 4, "문단을 문장 단위로 그대로"
    assert writer.split_sentences("gemini.google/desktop 에서 받아요. 1.5배 빨라요! 되나요? 네.") == \
        ["gemini.google/desktop 에서 받아요.", "1.5배 빨라요!", "되나요?", "네."]


def test_build_slides_and_render_from_plan():
    plan = {"cover": {"title": "제목\n둘째 줄", "sub": "부제", "image": None},
            "cards": [{"title": f"카드 {i}", "lines": ["핵심 A", "핵심 B"], "image": None, "image_caption": ""} for i in range(6)],
            "cta": "저장해 두세요"}
    slides = cards.build_slides(plan, "@aitips")
    assert [s["kind"] for s in slides] == ["cover"] + ["body"] * 6 + ["cta"]
    assert [s["n"] for s in slides] == list(range(1, 9)) and all(s["total"] == 8 for s in slides)
    slides[1]["highlights"] = ["핵심 A"]
    slides[1]["keyword"] = "Alt+Space"
    html = cards.render_html("dark_code", slides[1], {"accent": "#fff"})
    assert '<b class="hl">핵심 A</b>' in html and "Alt+Space" in html and "AI TIPS" in html and "@font-face" in html
    assert str(cards.mark_highlights("a <b> c", ["<b>"])) == 'a <b class="hl">&lt;b&gt;</b> c', "강조어도 이스케이프"
    assert cards.credit_of({"url": "https://cdn.x/1.jpg", "source_url": "https://www.aitimes.com/news/1", "kind": "related"}) == "사진: aitimes.com"


def test_image_candidates_never_use_social_media_images():
    main = {"title": "인스타 글", "images": [{"url": "https://scontent-sea5-1.cdninstagram.com/v/x.jpg", "alt": "a"}],
            "links": ["https://www.instagram.com/p/abc/", "https://openai.com/chatgpt"]}
    related = [{"link": "https://www.instagram.com/p/other/", "title": "다른 계정", "images": [{"url": "https://cdn.x/1.jpg", "alt": "n"}]},
               {"link": "https://www.aitimes.com/news/1", "title": "기사", "images": [{"url": "https://cdn.aitimes.com/1.jpg", "alt": "n"}]}]
    c = research.image_candidates(main, related, main_url="https://www.instagram.com/p/abc/",
                                  extra_links=["https://openai.com/index/x", "https://help.openai.com/y", "https://www.threads.net/z"])
    urls = [x["url"] for x in c]
    assert not any(research.is_social(u.replace("screenshot:", "")) for u in urls), urls
    assert "https://cdn.aitimes.com/1.jpg" in urls
    assert "screenshot:https://openai.com/chatgpt" in urls and "screenshot:https://help.openai.com/y" in urls
    assert "screenshot:https://www.aitimes.com/news/1" not in urls, "언론사 페이지는 캡처하지 않는다"
    assert "screenshot:https://openai.com/index/x" not in urls, "출처 캡처는 도메인당 하나"
    assert research.credit_of if False else cards.credit_of({"kind": "cc", "source_title": "Jane · CC BY"}) == "사진: Jane · CC BY"


def test_image_candidates_order_and_numbering():
    main = {"title": "원문", "images": [{"url": "https://a/1.jpg", "alt": "a"}], "links": ["https://openai.com/x"],
            "link_articles": [{"link": "https://openai.com/x", "title": "공식", "images": [{"url": "https://o/1.jpg", "alt": "o"}]}]}
    related = [{"link": "https://news/1", "title": "기사", "images": [{"url": "https://n/1.jpg", "alt": "n"}, {"url": "https://a/1.jpg", "alt": "dup"}]}]
    c = research.image_candidates(main, related, main_url="https://blog.google/a")
    assert [x["id"] for x in c] == [1, 2, 3, 4, 5]
    assert [x["kind"] for x in c] == ["official", "official", "related", "screenshot", "screenshot"]
    assert c[3]["url"] == "screenshot:https://openai.com/x" and c[4]["url"] == "screenshot:https://blog.google/a"
    assert research.image_candidates(main, [], main_url="https://www.pcworld.com/a")[-1]["url"] != "screenshot:https://www.pcworld.com/a", "언론사 원문은 캡처 안 함"


def test_extract_prompt_and_chat_bubble():
    assert writer.extract_prompt("이렇게 입력해 보세요. '표에 있는 사이트마다 삭제 요청문을 써서 제출해 줘.' 에이전트는 허락을 구해요.") == "표에 있는 사이트마다 삭제 요청문을 써서 제출해 줘."
    assert writer.extract_prompt("‘옵터리(Optery)’ 같은 서비스도 있어요.") == "", "짧은 인용은 프롬프트가 아님"
    plan = {"cover": {"title": "t", "sub": "s", "image": None},
            "cards": [{"title": "c", "lines": ["a"], "prompt": "내 정보가 공개된 사이트를 표로 정리해 줘", "image": None}], "cta": "x"}
    html = cards.render_html("dark_code", cards.build_slides(plan, "@a")[1], {"accent": "#fff"})
    assert 'class="chat"' in html and "표로 정리해 줘" in html
    assert writer.strip_prompt("이렇게 입력해 보세요. '사이트를 표로 정리해 줘.' 표가 나오면 표시해 두세요.", "사이트를 표로 정리해 줘.") == "이렇게 입력해 보세요. 표가 나오면 표시해 두세요."
    assert research.is_official("https://help.openai.com/en/articles/1") and not research.is_official("https://www.pcworld.com/x")


def test_korean_mock_renders_and_english_mock_is_dropped():
    assert writer.clean_mock({"app": "ChatGPT", "user": "Find my data", "assistant": ["site A | info"]}) is None, "영어 목업은 버린다"
    m = writer.clean_mock({"app": "ChatGPT", "user": "내 정보가 공개된 사이트를 표로 정리해 줘", "assistant": ["사이트 | 노출 정보 | 삭제 링크", "사람찾기 A | 이름·주소 | 삭제 요청", "B | 전화번호 | 삭제 요청"]})
    assert m and m["app"] == "ChatGPT"
    plan = {"cover": {"title": "제목", "sub": "s", "image": None, "mock": m}, "cards": [{"title": "c", "lines": ["a"], "image": None, "mock": m}], "cta": "x"}
    slides = cards.build_slides(plan, "@a")
    html = cards.render_html("dark_code", slides[0], {"accent": "#fff"})
    assert 'class="phone"' in html and "<table>" in html and "사람찾기 A" in html and "예시 화면" in html
    assert research.is_korean_source("https://www.aitimes.com/x", "제미나이 출시") and not research.is_korean_source("https://www.pcworld.com/x", "The Optery Guide")


def test_plan_cards_uses_cc_photo_from_image_query_when_nothing_picked(monkeypatch):
    p = profile(cc_photos=True)
    calls = []

    def fake_openverse(query, *, n=3, **kw):
        calls.append(query)
        return [{"url": f"https://cc/{query.replace(' ', '_')}.jpg", "alt": query, "source_url": "https://flickr/x",
                 "source_title": "Jane · CC BY", "kind": "cc"}]

    monkeypatch.setattr(research, "openverse_search", fake_openverse)
    plan_json = {"cover": {"title": "제목", "sub": "s", "image_id": 0, "image_query": "laptop privacy"},
                 "cards": [{"image_id": 0, "image_query": f"concept {i}"} for i in range(6)], "cta": "저장"}

    class Fake:
        last_provider = "fake"

        def json(self, *, system, user, schema=None):
            return json.loads(json.dumps(plan_json))

    plan = writer.plan_cards(Fake(), p, sample_article(), [], progress=lambda m: None)
    assert plan["cover"]["image"]["kind"] == "cc" and plan["cover"]["image"]["url"].endswith("laptop_privacy.jpg")
    assert writer.plan_cards(Fake(), profile(), sample_article(), [], progress=lambda m: None)["cover"]["image"] is None, "기본은 CC 검색 끔"
    assert [c["image"]["kind"] if c["image"] else None for c in plan["cards"]] == ["cc"] * 4 + [None, None], "앞 4장만 개념 사진"
    assert len(set(c["image"]["url"] for c in plan["cards"] if c["image"])) == 4, "같은 사진 반복 없음"


def test_plan_cards_falls_back_to_screenshot_cover_when_no_image_picked():
    p = profile()
    images = [{"id": 1, "url": "screenshot:https://src/a", "alt": "캡처", "source_url": "https://src/a",
               "source_title": "원문", "kind": "screenshot"}]
    plan_json = {"cover": {"title": "제목", "sub": "s", "image_id": 0},
                 "cards": [{"image_id": 0} for _ in range(6)], "cta": "저장"}

    class Fake:
        last_provider = "fake"

        def json(self, *, system, user, schema=None):
            return plan_json

    plan = writer.plan_cards(Fake(), p, sample_article(), images, progress=lambda m: None)
    assert plan["cover"]["image"]["kind"] == "screenshot"


def test_publish_carousel_flow_with_fake_session():
    class FakeResp:
        def __init__(self, data, ok=True, status=200):
            self._d, self.ok, self.status_code, self.text = data, ok, status, json.dumps(data)

        def json(self):
            return self._d

    seen = []

    class FakeSession:
        def request(self, method, url, params=None, data=None, timeout=None):
            seen.append((method, url.split("/v23.0/")[1], data or params))
            path = url.split("/v23.0/")[1]
            if path == "me":
                return FakeResp({"user_id": "777", "username": "aitips"})
            if path.endswith("/media_publish"):
                return FakeResp({"id": "M1"})
            if path.endswith("/media"):
                return FakeResp({"id": f"C{len(seen)}"})
            if "fields" in (params or {}) and params["fields"].startswith("status"):
                return FakeResp({"status_code": "FINISHED"})
            return FakeResp({"permalink": "https://www.instagram.com/p/abc/"})

    ig = pub.Instagram("tok", "", session=FakeSession())
    assert ig.user_id == "777"
    res = pub.publish_carousel(ig, ["https://cdn/1.jpg", "https://cdn/2.jpg"], "캡션", progress=lambda m: None)
    assert res == {"media_id": "M1", "permalink": "https://www.instagram.com/p/abc/"}
    kinds = [s[1] for s in seen]
    assert kinds.count("777/media") == 3 and "777/media_publish" in kinds
    carousel = [s for s in seen if s[1] == "777/media" and (s[2] or {}).get("media_type") == "CAROUSEL"][0]
    assert carousel[2]["children"].count(",") == 1


def test_missing_token_is_clear():
    with pytest.raises(pub.MissingInstaToken):
        pub.Instagram("", "1")


def test_watch_candidates_from_captions_sorted_by_likes(monkeypatch):
    monkeypatch.setenv("IG_DISCOVERY_TOKEN", "t")
    monkeypatch.setenv("IG_DISCOVERY_USER_ID", "1")
    posts = {"ai.trend.kr": [
        {"caption": "나만 빼고 다 아는 챗GPT 명령어 100개 받아가세요. 🔥\n오픈AI가…", "permalink": "https://www.instagram.com/p/A/", "timestamp": "2026-09-10T01:00:00+0000", "like_count": 33000, "comments_count": 16000},
        {"caption": "#광고 협찬 게시물", "permalink": "https://www.instagram.com/p/B/", "timestamp": "2026-09-10T02:00:00+0000", "like_count": 500, "comments_count": 3},
    ]}
    monkeypatch.setattr(watch, "fetch_account", lambda acct, **kw: posts[acct])
    found, failed = watch.collect_watch(["ai.trend.kr"], min_likes=1000, now=datetime(2026, 9, 11, tzinfo=timezone.utc), progress=lambda m: None)
    assert failed == [] and len(found) == 1
    assert found[0].title == "나만 빼고 다 아는 챗GPT 명령어 100개 받아가세요"
    assert "좋아요 3.3만" in found[0].source and watch.likes_of(found[0]) == 33000


def test_watch_foreign_flag_and_cap(monkeypatch):
    monkeypatch.setenv("IG_DISCOVERY_TOKEN", "t")
    monkeypatch.setenv("IG_DISCOVERY_USER_ID", "1")
    posts = {"openai": [
        {"caption": f"Post {i}", "permalink": f"https://www.instagram.com/p/F{i}/", "timestamp": "2026-09-10T01:00:00+0000", "like_count": 100 * i, "comments_count": 0}
        for i in range(1, 5)] + [
        {"caption": "Comment “Agent” and we’ll DM you the link", "permalink": "https://www.instagram.com/p/G/", "timestamp": "2026-09-10T01:00:00+0000", "like_count": 99999, "comments_count": 0}],
        "small": [{"caption": f"S {i}", "permalink": f"https://www.instagram.com/p/S{i}/", "timestamp": "2026-09-10T01:00:00+0000", "like_count": i, "comments_count": 0} for i in range(1, 4)]}
    monkeypatch.setattr(watch, "fetch_account", lambda acct, **kw: posts[acct])
    found, _ = watch.collect_watch(["openai"], flag="🇺🇸", cap=2, now=datetime(2026, 9, 11, tzinfo=timezone.utc), progress=lambda m: None)
    assert [c.title for c in found] == ["Post 4", "Post 3"] and found[0].source.startswith("IG 🇺🇸 @openai"), "댓글 유도 게시물은 제외"
    both, _ = watch.collect_watch(["openai", "small"], per_account=2, now=datetime(2026, 9, 11, tzinfo=timezone.utc), progress=lambda m: None)
    assert [c.title for c in both] == ["Post 4", "Post 3", "S 3", "S 2"], "계정당 상한"
    assert watch.SKIP_RE.search("오늘은 #광고 힉스필드") and watch.SKIP_RE.search("(제작지원 higgsfield.ai)")
    assert {"deepmind", "rundown", "testingcatalog", "techcrunch_ai"} <= set(sources.SOURCES)


def test_collect_signal_required_and_exclude_words(monkeypatch):
    items = [cand("강원도 독감 무료 예방접종 확대", 1, "https://x.test/a"), cand("[인사] 보건복지부", 1, "https://x.test/b"),
             cand("중흥그룹 추석 협력사 대금 지급", 1, "https://x.test/c")]
    monkeypatch.setattr(sources, "fetch_source", lambda name, **kw: items)
    found, _ = sources.collect(["yna_society"], max_age_hours=72, signals=["무료", "신청"], exclude_keys=set(), progress=lambda m: None,
                               signal_required=["yna_society"], exclude_words=["[인사]"])
    assert [c.title for c in found] == ["강원도 독감 무료 예방접종 확대"], "신호 없는 글·제외어 글은 빠진다"


def test_all_profiles_load_and_their_sources_exist():
    import yaml

    for f in (Path(__file__).resolve().parent.parent / "profiles").glob("*.yaml"):
        d = yaml.safe_load(f.read_text(encoding="utf-8"))
        p = writer.Profile.from_dict(d)
        assert p.name and p.sources, f.name
        for s in p.sources:
            assert s in sources.SOURCES, f"{f.name}: 모르는 출처 {s}"
        if d.get("references"):
            assert (Path(__file__).resolve().parent.parent / d["references"]).exists(), f.name
        sys_, _ = writer.pick_prompt(p, "1. x", 3)
        assert "편집장" in sys_


def test_watch_skips_quietly_without_token(monkeypatch):
    monkeypatch.delenv("IG_DISCOVERY_TOKEN", raising=False)
    msgs = []
    assert watch.collect_watch(["ai.trend.kr"], progress=msgs.append) == ([], [])
    assert msgs and "IG_DISCOVERY_TOKEN" in msgs[0]


def test_cap_by_source_limits_noisy_sources():
    items = [cand(f"r{i}", 1, f"https://x.test/r{i}") for i in range(4)]
    for c in items:
        c.source = "r/ChatGPT"
    items.append(cand("o", 1, "https://x.test/o"))
    out = sources.cap_by_source(items, {"reddit_chatgpt": 2})
    assert [c.title for c in out] == ["r0", "r1", "o"]
