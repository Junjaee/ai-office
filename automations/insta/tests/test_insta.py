"""insta 자동화 — 오프라인으로 검사할 수 있는 부분: 소재 걸러내기, JSON 추출·스키마, 로컬 검사, 카드 슬라이드 구성, 게시 흐름(가짜 API)."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))

import insta_cards as cards  # noqa: E402
import insta_publisher as pub  # noqa: E402
import insta_sources as sources  # noqa: E402
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


def sample_post():
    return {"hook": "챗GPT 명령어 3개", "sub": "몰라서 못 쓰던 것", "cta": "저장",
            "slides": [{"title": f"팁 {i}", "body": "짧은 설명 한 줄", "code": "/human"} for i in range(6)],
            "caption": "훅 반복\n\n핵심 요약 문장을 조금 길게 써서 길이 조건을 채웁니다. 실제로는 삼백 자 안팎으로 씁니다.\n\n저장해 두세요.",
            "hashtags": ["AI활용", "#챗GPT", "#프롬프트"], "alt_text": "카드뉴스",
            "sources": ["https://openai.com/x"], "claims": [{"text": "명령어 24개", "source": "https://openai.com/x"}]}


def test_local_checks_flag_banned_and_missing_sources_and_fix_hashtags():
    p = writer.Profile.from_dict({"name": "t", "audience": "a", "tone": "t", "format": "list", "slides": 8,
                                  "hook_patterns": [], "must_include": [], "banned": ["게임체인저"], "cta": "c",
                                  "hashtags_base": [], "sources": [], "source_signals": [], "template": "dark_code",
                                  "judge_weights": {}, "pass_score": 38})
    post = sample_post()
    assert writer.local_checks(p, post) == []
    assert post["hashtags"][0] == "#AI활용"
    post["slides"][0]["body"] = "게임체인저"
    post["claims"][0]["source"] = "출처 없음"
    problems = writer.local_checks(p, post)
    assert any("금지" in x for x in problems) and any("URL" in x for x in problems)


def test_generate_post_revises_until_pass(monkeypatch):
    p = writer.Profile.from_dict({"name": "t", "audience": "a", "tone": "t", "format": "list", "slides": 8,
                                  "hook_patterns": ["x"], "must_include": ["y"], "banned": [], "cta": "c",
                                  "hashtags_base": ["#a"], "sources": [], "source_signals": [], "template": "dark_code",
                                  "judge_weights": {"hook": 2}, "pass_score": 38})
    seq = iter([sample_post(), {"scores": {}, "total": 20, "verdict": "revise", "feedback": "훅 약함"},
                sample_post(), {"scores": {}, "total": 45, "verdict": "pass", "feedback": ""}])
    prompts = []

    class Fake:
        last_provider = "fake"

        def json(self, *, system, user, schema=None):
            prompts.append(user)
            return next(seq)

    post, verdict = writer.generate_post(Fake(), p, "refs", {"title": "t", "source": "s", "link": "l"}, "angle", progress=lambda m: None)
    assert verdict["verdict"] == "pass"
    assert "훅 약함" in prompts[2], "2차 원고 요청에 피드백이 붙는다"


def test_build_slides_has_cover_body_cta_numbering():
    slides = cards.build_slides(sample_post(), "@aitips")
    assert [s["kind"] for s in slides] == ["cover"] + ["body"] * 6 + ["cta"]
    assert [s["n"] for s in slides] == list(range(1, 9)) and all(s["total"] == 8 for s in slides)
    html = cards.render_html("dark_code", slides[1], {"accent": "#fff"})
    assert "팁 0" in html and "/human" in html and "@font-face" in html


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
