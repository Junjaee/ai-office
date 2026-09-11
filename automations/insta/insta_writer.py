"""글 생성 — 주제 프로필 + 참고 원고 + 선정 소재 → 카드 원고·캡션·해시태그 (JSON), 그리고 자동 심사.

프롬프트는 프로필(yaml)의 값으로 채운다. 주제가 바뀌어도 이 파일은 그대로다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from insta_llm import LLM

POST_SCHEMA = {
    "type": "object",
    "required": ["hook", "sub", "slides", "cta", "caption", "hashtags", "alt_text", "sources", "claims"],
    "properties": {
        "hook": {"type": "string", "minLength": 4, "maxLength": 40},
        "sub": {"type": "string", "maxLength": 80},
        "slides": {
            "type": "array", "minItems": 4, "maxItems": 9,
            "items": {"type": "object", "required": ["title", "body"],
                      "properties": {"title": {"type": "string", "maxLength": 40},
                                     "body": {"type": "string", "maxLength": 220},
                                     "code": {"type": "string", "maxLength": 120}}},
        },
        "cta": {"type": "string", "maxLength": 80},
        "caption": {"type": "string", "minLength": 80, "maxLength": 1200},
        "hashtags": {"type": "array", "minItems": 3, "maxItems": 8, "items": {"type": "string"}},
        "alt_text": {"type": "string", "maxLength": 200},
        "sources": {"type": "array", "items": {"type": "string"}},
        "claims": {"type": "array", "items": {"type": "object", "required": ["text", "source"],
                                              "properties": {"text": {"type": "string"}, "source": {"type": "string"}}}},
    },
}

PICK_SCHEMA = {
    "type": "object",
    "required": ["picks"],
    "properties": {"picks": {"type": "array", "minItems": 1, "maxItems": 3,
                             "items": {"type": "object", "required": ["index", "reason", "angle"],
                                       "properties": {"index": {"type": "integer"}, "reason": {"type": "string"},
                                                      "angle": {"type": "string"}}}}},
}

JUDGE_SCHEMA = {
    "type": "object",
    "required": ["scores", "total", "verdict", "feedback"],
    "properties": {"scores": {"type": "object"}, "total": {"type": "number"},
                   "verdict": {"type": "string", "enum": ["pass", "revise"]}, "feedback": {"type": "string"}},
}


@dataclass
class Profile:
    """profiles/<이름>.yaml 을 읽은 것. 필드 이름은 yaml 키와 같다."""
    name: str
    audience: str
    tone: str
    format: str
    slides: int
    hook_patterns: list[str]
    must_include: list[str]
    banned: list[str]
    cta: str
    hashtags_base: list[str]
    sources: list[str]
    source_signals: list[str]
    template: str
    judge_weights: dict
    pass_score: int
    handle: str = ""
    theme: dict | None = None
    max_age_hours: int = 72

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


def _rules(p: Profile) -> str:
    return "\n".join([
        f"- 독자: {p.audience}",
        f"- 말투: {p.tone}",
        f"- 형식: {p.format} (카드 {p.slides}장: 표지 1 + 본문 {p.slides - 2} + 마무리 1)",
        "- 카드 한 장 본문은 15~25단어. 표지는 한 줄 훅(15자 안팎) + 보조 문장 한 줄.",
        "- 첫 3장은 각각 독립적으로 흥미를 끌어야 한다(스크롤을 멈추는 미끼 3개).",
        f"- 훅 패턴 예: {', '.join(p.hook_patterns)}",
        f"- 반드시 포함: {', '.join(p.must_include)}",
        f"- 금지 표현: {', '.join(p.banned)}. 느낌표 남발·이모지는 카드당 1개 이하.",
        "- 숫자·툴 이름·명령어는 출처 그대로. 출처에 없는 사실을 지어내지 않는다.",
        "- 모든 사실 주장은 claims 에 {text, source(URL)} 로 넣는다. 출처를 못 대는 주장은 쓰지 않는다. 원문·공식 링크에 없는 세부(요금, 지원 OS, 날짜)는 단정하지 말고 '공식 안내 확인'으로 돌린다.",
        "- code 칸은 실제로 입력할 명령·프롬프트·단축키만 넣는다. 안내 문구나 '확인하세요' 같은 말은 code 에 넣지 않는다(없으면 비운다).",
        f"- 마지막 장(cta): {p.cta}",
        "- caption: 300~450자, 3문단(첫 줄이 훅 반복 → 핵심 요약 → 저장·공유 유도). 해시태그는 caption 에 넣지 말고 hashtags 배열로.",
        f"- hashtags: 기본 {', '.join(p.hashtags_base)} 중 3개 + 소재에 맞는 2개, 총 5개 안팎.",
        "- alt_text: 시각장애인용 한 문장 설명.",
    ])


def pick_prompt(p: Profile, rows: str, n: int) -> tuple[str, str]:
    system = (f"당신은 인스타그램 정보 계정 '{p.name}'의 편집장입니다. 독자: {p.audience}\n"
              "후보 목록에서 오늘 게시할 소재를 고릅니다. 선정 기준: 독자가 바로 써먹을 수 있는가, 저장하고 싶은가, 새로운가, "
              "한 장짜리 카드 8장으로 풀 수 있는가. 광고·모금·행사 안내·기업 실적 뉴스는 제외.\n"
              "도구를 쓰지 말고 JSON 객체 하나만 출력합니다.")
    user = (f"후보:\n{rows}\n\n"
            f"가장 좋은 {n}개를 고르고 각각 index(후보 번호), reason(선정 이유 한 줄), angle(카드로 풀 때의 각도 한 줄)을 적으세요.\n"
            'JSON: {"picks": [{"index": 3, "reason": "...", "angle": "..."}]}')
    return system, user


def write_prompt(p: Profile, refs: str, cand: dict, angle: str, best_own: str = "") -> tuple[str, str]:
    system = (f"당신은 인스타그램 정보 계정 '{p.name}'({p.handle})의 카드뉴스 작가입니다.\n"
              "아래 규칙을 지켜 카드 원고를 씁니다.\n" + _rules(p) +
              "\n\n[잘 된 게시물 예시 — 결과 구조와 톤을 참고하되 문장은 베끼지 않는다]\n" + refs +
              (f"\n\n[우리 계정에서 성과가 좋았던 글]\n{best_own}" if best_own else "") +
              "\n\n도구를 쓰지 말고 JSON 객체 하나만 출력합니다.")
    article = cand.get("article") or {}
    extra = ""
    if article.get("text"):
        extra += f"\n원문 발췌(여기 있는 사실만 쓴다):\n{article['text']}\n"
    if article.get("links"):
        extra += "원문이 가리키는 바깥 링크(공식 출처가 있으면 claims 의 source 로 우선 사용):\n" + "\n".join(article["links"]) + "\n"
    user = (f"오늘 소재:\n제목: {cand['title']}\n출처: {cand['source']} {cand['link']}\n"
            f"요약: {cand.get('summary', '')}\n각도: {angle}\n{extra}\n"
            "다음 키를 가진 JSON 을 출력하세요: hook, sub, slides[{title, body, code?}], cta, caption, hashtags[], alt_text, "
            "sources[], claims[{text, source}]. slides 는 본문 카드만(표지·마무리 제외) "
            f"{p.slides - 2}장.")
    return system, user


def judge_prompt(p: Profile, post: dict) -> tuple[str, str]:
    w = p.judge_weights
    system = ("당신은 인스타그램 카드뉴스 품질 심사관입니다. 냉정하게 채점합니다. 도구를 쓰지 말고 JSON 만 출력합니다.\n"
              "채점 항목(각 1~5점): hook(첫 장이 스크롤을 멈추는가, 구체적인가), useful(독자가 바로 써먹는가), "
              "factual(주장마다 출처가 있고 과장이 없는가), korean(자연스러운 한국어, AI 티 나는 표현 없음), "
              "rules(카드 길이·금지어·형식 규칙 준수).\n"
              f"가중치: {json.dumps(w, ensure_ascii=False)}. total = Σ(점수×가중치). "
              f"total ≥ {p.pass_score} 이면 verdict=pass, 아니면 revise 와 함께 고칠 점을 feedback 에 구체적으로.")
    user = ("원고:\n" + json.dumps(post, ensure_ascii=False, indent=1) +
            f"\n\n금지 표현: {', '.join(p.banned)}\n"
            'JSON: {"scores": {"hook": n, "useful": n, "factual": n, "korean": n, "rules": n}, "total": n, "verdict": "pass|revise", "feedback": "..."}')
    return system, user


def local_checks(p: Profile, post: dict) -> list[str]:
    """모델을 부르기 전에 코드로 잡는 문제들."""
    problems = []
    text = json.dumps(post, ensure_ascii=False)
    for b in p.banned:
        if b and b in text:
            problems.append(f"금지 표현 '{b}' 포함")
    if not post.get("claims"):
        problems.append("claims 비어 있음(출처 있는 주장이 없음)")
    for c in post.get("claims", []):
        if not str(c.get("source", "")).startswith("http"):
            problems.append(f"출처가 URL 이 아님: {c.get('source')}")
            break
    for i, s in enumerate(post.get("slides", []), 1):
        words = len(str(s.get("body", "")).split())
        if words > 45:
            problems.append(f"{i}번 카드 본문이 너무 김({words}단어)")
    post["hashtags"] = ["#" + str(h).strip().lstrip("#") for h in post.get("hashtags", []) if str(h).strip()]
    return problems


def generate_post(llm: LLM, p: Profile, refs: str, cand: dict, angle: str, *, best_own: str = "",
                  max_rounds: int = 2, seed_feedback: str = "", progress=print) -> tuple[dict, dict]:
    """원고 생성 → 코드 검사 → 모델 심사 → 필요하면 피드백 붙여 재생성. (원고, 심사결과) 반환.
    seed_feedback 이 있으면(다듬기) 첫 회부터 그 피드백을 반영해 쓴다."""
    system, user = write_prompt(p, refs, cand, angle, best_own)
    feedback = seed_feedback
    post: dict = {}
    verdict: dict = {}
    for round_no in range(1, max_rounds + 1):
        prompt = user + (f"\n\n[이전 원고 심사 피드백 — 반영해서 다시 쓰세요]\n{feedback}" if feedback else "")
        post = llm.json(system=system, user=prompt, schema=POST_SCHEMA)
        problems = local_checks(p, post)
        js, ju = judge_prompt(p, post)
        verdict = llm.json(system=js, user=ju, schema=JUDGE_SCHEMA)
        if problems:
            verdict["verdict"] = "revise"
            verdict["feedback"] = "; ".join(problems) + " / " + str(verdict.get("feedback", ""))
        progress(f"원고 {round_no}차: {verdict.get('total')}점 → {verdict.get('verdict')}")
        if verdict.get("verdict") == "pass":
            break
        feedback = str(verdict.get("feedback", ""))
    return post, verdict
