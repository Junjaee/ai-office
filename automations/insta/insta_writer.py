"""글 생성 — 기사 한 편을 쓰고(어그로 제목 + 소주제별 문단), 글쓰기 전문가가 검수하고, 문단마다 카드 한 장으로 요약한다.

흐름 (사용자 결정 2026-09-11):
  1) 검색어 뽑기 → 같은 주제의 기사·블로그 조사 (insta_research)
  2) 기사 쓰기: 제목(어그로) + 부제 + 문단 5~7개, 문단마다 소주제 하나·3~4줄
  3) 검수: 글쓰기 전문가가 가독성·흥미·사실·구조를 채점, 미달이면 지적을 붙여 다시 쓴다
  4) 카드 요약: 표지(제목) + 문단마다 카드 1장(핵심만, 토씨 다 옮기지 않음) + 어울리는 사진 번호
프롬프트는 프로필(yaml)의 값으로 채운다. 주제가 바뀌어도 이 파일은 그대로다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from insta_llm import LLM

QUERY_SCHEMA = {
    "type": "object", "required": ["queries"],
    "properties": {"queries": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string", "maxLength": 60}}},
}

PICK_SCHEMA = {
    "type": "object",
    "required": ["picks"],
    "properties": {"picks": {"type": "array", "minItems": 1, "maxItems": 3,
                             "items": {"type": "object", "required": ["index", "reason", "angle"],
                                       "properties": {"index": {"type": "integer"}, "reason": {"type": "string"},
                                                      "angle": {"type": "string"}}}}},
}

ARTICLE_SCHEMA = {
    "type": "object",
    "required": ["title", "subtitle", "paragraphs", "caption", "hashtags", "alt_text", "sources", "claims"],
    "properties": {
        "title": {"type": "string", "minLength": 6, "maxLength": 40},
        "subtitle": {"type": "string", "maxLength": 70},
        "paragraphs": {
            "type": "array", "minItems": 4, "maxItems": 8,
            "items": {"type": "object", "required": ["heading", "text"],
                      "properties": {"heading": {"type": "string", "maxLength": 30},
                                     "text": {"type": "string", "minLength": 60, "maxLength": 320}}},
        },
        "caption": {"type": "string", "minLength": 80, "maxLength": 1500},
        "hashtags": {"type": "array", "minItems": 3, "maxItems": 8, "items": {"type": "string"}},
        "alt_text": {"type": "string", "maxLength": 200},
        "sources": {"type": "array", "items": {"type": "string"}},
        "claims": {"type": "array", "items": {"type": "object", "required": ["text", "source"],
                                              "properties": {"text": {"type": "string"}, "source": {"type": "string"}}}},
    },
}

EDITOR_SCHEMA = {
    "type": "object",
    "required": ["scores", "total", "verdict", "feedback"],
    "properties": {"scores": {"type": "object"}, "total": {"type": "number"},
                   "verdict": {"type": "string", "enum": ["pass", "revise"]}, "feedback": {"type": "string"},
                   "better_titles": {"type": "array", "items": {"type": "string"}}},
}

CARDS_SCHEMA = {
    "type": "object",
    "required": ["cover", "cards", "cta"],
    "properties": {
        "cover": {"type": "object", "required": ["title", "sub"],
                  "properties": {"title": {"type": "string", "maxLength": 48}, "sub": {"type": "string", "maxLength": 80},
                                 "image_id": {"type": "integer"}, "category": {"type": "string", "maxLength": 24}}},
        "cards": {
            "type": "array", "minItems": 1, "maxItems": 9,
            "items": {"type": "object", "required": ["image_id"],
                      "properties": {"image_id": {"type": "integer"},
                                     "image_caption": {"type": "string", "maxLength": 60},
                                     "keyword": {"type": "string", "maxLength": 24},
                                     "highlights": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 30}}}},
        },
        "cta": {"type": "string", "maxLength": 80},
    },
}


@dataclass
class Profile:
    """profiles/<이름>.yaml 을 읽은 것. 필드 이름은 yaml 키와 같다."""
    name: str
    audience: str
    tone: str
    format: str
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
    paragraphs: int = 6                 # 기사 문단 수 (= 본문 카드 수)
    title_patterns: list[str] | None = None
    slides: int = 0                     # (구버전 호환) 쓰지 않음
    hook_patterns: list[str] | None = None
    flow: dict | None = None
    images_per_post: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


# ───────────────────────── 1) 소재 고르기 / 검색어 ─────────────────────────

def pick_prompt(p: Profile, rows: str, n: int) -> tuple[str, str]:
    system = (f"당신은 인스타그램 정보 계정 '{p.name}'의 편집장입니다. 독자: {p.audience}\n"
              "후보 목록에서 오늘 게시할 소재를 고릅니다. 선정 기준: 독자가 바로 써먹을 수 있는가, 저장하고 싶은가, 새로운가, "
              "기사 한 편(문단 5~7개)으로 풀 수 있는가. 광고·모금·행사 안내·기업 실적 뉴스는 제외.\n"
              "**카드에 넣을 실제 화면·제품 사진을 구할 수 있는 소재를 우선**한다: 공식 블로그·제품 페이지·언론 기사가 있는 출시·업데이트 소식이 "
              "커뮤니티 글(reddit 등)보다 우선. 커뮤니티 글은 공식 링크나 결과물 이미지가 딸려 있을 때만 고른다.\n"
              "도구를 쓰지 말고 JSON 객체 하나만 출력합니다.")
    user = (f"후보:\n{rows}\n\n"
            f"가장 좋은 {n}개를 고르고 각각 index(후보 번호), reason(선정 이유 한 줄), angle(기사로 풀 때의 각도 한 줄)을 적으세요.\n"
            'JSON: {"picks": [{"index": 3, "reason": "...", "angle": "..."}]}')
    return system, user


def query_prompt(cand: dict) -> tuple[str, str]:
    system = ("당신은 리서처입니다. 아래 소재와 같은 내용을 다룬 한국어 기사·블로그 글을 찾기 위한 뉴스 검색어를 만듭니다. "
              "도구를 쓰지 말고 JSON 만 출력합니다.")
    user = (f"소재 제목: {cand['title']}\n요약: {cand.get('summary', '')[:300]}\n\n"
            "검색어 3개: 한국어 2개(제품·기능 이름은 한글 표기, 예 '제미나이 윈도우 앱'), 영어 1개(공식 명칭). 각 2~5단어.\n"
            'JSON: {"queries": ["...", "...", "..."]}')
    return system, user


# ───────────────────────── 2) 기사 쓰기 ─────────────────────────

def _article_rules(p: Profile) -> str:
    pats = p.title_patterns or ["'<누가>, <무엇> 출시' 같은 뉴스 헤드라인 + 독자 이득", "숫자형 '<툴> 기능 N개'", "질문형"]
    return "\n".join([
        f"- 독자: {p.audience}",
        f"- 말투: {p.tone}",
        "- 결과물은 인스타그램 카드뉴스의 바탕이 되는 **기사 한 편**이다. 카드 문구가 아니라 완결된 글로 쓴다.",
        f"- 제목(title): 스크롤을 멈추게 하는 제목. 다만 사실을 벗어난 낚시는 금지. 패턴 예: {' / '.join(pats)}. 20자 안팎.",
        "- 본문에 인상적인 **숫자·대비**(예: 22초 vs 177초, 8배, 무료, 하루 100장)가 있으면 제목이나 부제에 반드시 끌어온다. '완결편'·'총정리' 같은 밋밋한 말에만 기대지 않는다.",
        "- 부제(subtitle): 제목이 약속한 이득을 한 줄로.",
        f"- 문단(paragraphs) {p.paragraphs}개. **문단 하나 = 소주제 하나**. heading 은 그 소주제를 12자 안팎으로, text 는 3~4줄(90~200자) 완결된 문장.",
        "- 문단 순서: 독자가 궁금한 순서. 소식이면 '언제·누가·무엇 → 달라지는 점(장점) 여러 개 → 쓰는 법 → 받는 곳·조건' 순.",
        "- 문단마다 구체적인 예(숫자·화면·입력 예시)를 하나 이상 넣는다. 추상적인 설명만 있는 문단은 실패.",
        f"- 반드시 포함: {', '.join(p.must_include)}",
        f"- 금지 표현: {', '.join(p.banned)}. 느낌표 남발·이모지 금지(캡션은 문단당 1개 이하).",
        "- 숫자·툴 이름·명령어는 출처 그대로. 소재 원문·공식 링크·관련 글에 없는 사실은 쓰지 않는다. 확실치 않은 세부(요금·지원 OS·날짜)는 '공식 안내 확인' 으로 돌린다.",
        "- 모든 사실 주장은 claims 에 {text, source(URL)} 로 넣는다(공식 출처 우선).",
        "- caption: 인스타 본문. 300~500자, 3문단(첫 줄 = 제목 반복 → 핵심 요약 → 저장·공유 유도). 해시태그는 hashtags 배열로.",
        f"- hashtags: 기본 {', '.join(p.hashtags_base)} 중 3개 + 소재에 맞는 2개.",
        "- alt_text: 시각장애인용 한 문장.",
    ])


def article_prompt(p: Profile, refs: str, cand: dict, research: str, best_own: str = "") -> tuple[str, str]:
    system = (f"당신은 인스타그램 정보 계정 '{p.name}'({p.handle})의 기자 겸 작가입니다.\n"
              "아래 규칙을 지켜 기사 한 편을 씁니다.\n" + _article_rules(p) +
              "\n\n[잘 된 게시물 예시 — 흐름·호흡·첫 줄의 결을 참고하되 문장은 베끼지 않는다]\n" + refs +
              (f"\n\n[우리 계정에서 성과가 좋았던 글]\n{best_own}" if best_own else "") +
              "\n\n도구를 쓰지 말고 JSON 객체 하나만 출력합니다.")
    article = cand.get("article") or {}
    extra = ""
    if article.get("text"):
        extra += f"\n[소재 원문 발췌 — 1차 근거]\n{article['text']}\n"
    if article.get("links"):
        extra += "\n[원문이 가리키는 바깥 링크 — 공식 출처면 claims 의 source 로 우선 사용]\n" + "\n".join(article["links"]) + "\n"
    if research:
        extra += "\n[같은 주제를 다룬 다른 기사·블로그 — 어떤 점을 강조했고 어떤 순서로 풀었는지 참고. 사실은 원문·공식 출처와 맞는 것만]\n" + research + "\n"
    user = (f"오늘 소재:\n제목: {cand['title']}\n출처: {cand['source']} {cand['link']}\n"
            f"요약: {cand.get('summary', '')}\n각도: {cand.get('angle', '')}\n{extra}\n"
            "다음 키를 가진 JSON 을 출력하세요: title, subtitle, paragraphs[{heading, text}], caption, hashtags[], alt_text, "
            f"sources[], claims[{{text, source}}]. paragraphs 는 {p.paragraphs}개.")
    return system, user


# ───────────────────────── 3) 검수 (글쓰기 전문가) ─────────────────────────

def editor_prompt(p: Profile, article: dict) -> tuple[str, str]:
    w = p.judge_weights
    system = ("당신은 20년 차 글쓰기 전문가이자 인스타그램 정보 계정 편집장입니다. 아래 기사를 독자 입장에서 냉정하게 검수합니다. "
              "도구를 쓰지 말고 JSON 만 출력합니다.\n"
              "채점 항목(각 1~5점):\n"
              "- readability(가독성): 문장이 짧고 쉬운가, 한 문단에 한 소주제만 있는가, 3~4줄 호흡이 지켜지는가, AI 티 나는 표현이 없는가\n"
              "- interest(흥미): 제목이 스크롤을 멈추는가(낚시 아님), 첫 문단이 계속 읽게 하는가, 독자가 저장·공유하고 싶은가\n"
              "- factual(사실): 주장마다 출처가 있고 과장·추측이 없는가, 숫자·이름이 출처와 같은가\n"
              "- structure(구조): 문단 순서가 독자가 궁금한 순서인가, 문단마다 구체적 예가 있는가, 카드 한 장씩으로 나눠도 각각 뜻이 통하는가\n"
              f"가중치: {json.dumps(w, ensure_ascii=False)}. total = Σ(점수×가중치). "
              f"total ≥ {p.pass_score} 이면 verdict=pass. 단 **사실 오류**(출처에 없는 숫자·날짜·기능을 지어냄, 출처와 다른 주장)가 하나라도 있으면 "
              "점수와 무관하게 revise — '요금은 공식 안내 확인' 처럼 단정을 피한 안전한 문구는 오류가 아니다. "
              "구조·표현 지적(소주제 섞임, 반복, 밋밋한 도입 등)은 점수에만 반영하고 feedback 에 적는다. "
              "revise 면 어느 문단의 무엇을 어떻게 고칠지 구체적으로(고친 문장을 직접 써 준다). pass 여도 더 좋아질 점은 feedback 에 짧게. "
              "제목이 약하면 better_titles 에 대안 2~3개.")
    user = ("기사:\n" + json.dumps({k: article.get(k) for k in ("title", "subtitle", "paragraphs", "caption", "claims")},
                                  ensure_ascii=False, indent=1) +
            f"\n\n금지 표현: {', '.join(p.banned)}\n"
            'JSON: {"scores": {"readability": n, "interest": n, "factual": n, "structure": n}, "total": n, '
            '"verdict": "pass|revise", "feedback": "...", "better_titles": ["..."]}')
    return system, user


def local_checks(p: Profile, article: dict) -> list[str]:
    """모델을 부르기 전에 코드로 잡는 문제들."""
    problems = []
    text = json.dumps(article, ensure_ascii=False)
    for b in p.banned:
        if b and b in text:
            problems.append(f"금지 표현 '{b}' 포함")
    if not article.get("claims"):
        problems.append("claims 비어 있음(출처 있는 주장이 없음)")
    for c in article.get("claims", []):
        if not str(c.get("source", "")).startswith("http"):
            problems.append(f"출처가 URL 이 아님: {c.get('source')}")
            break
    paras = article.get("paragraphs", [])
    if p.paragraphs and abs(len(paras) - p.paragraphs) > 1:
        problems.append(f"문단이 {len(paras)}개 — {p.paragraphs}개 안팎으로")
    for i, para in enumerate(paras, 1):
        n = len(str(para.get("text", "")))
        if n < 70:
            problems.append(f"{i}번 문단이 너무 짧음({n}자) — 3~4줄(90~200자)")
        elif n > 260:
            problems.append(f"{i}번 문단이 너무 김({n}자) — 3~4줄(90~200자)")
    article["hashtags"] = ["#" + str(h).strip().lstrip("#") for h in article.get("hashtags", []) if str(h).strip()]
    return problems


def _revise_block(article: dict | None, feedback: str) -> str:
    """재작성 요청에 붙일 블록: 이전 기사가 있으면 그것을 주고 지적된 부분만 고치게 한다."""
    if not feedback:
        return ""
    block = "\n\n[검수관 지적 — 반드시 반영]\n" + feedback
    if article:
        keep = {k: article.get(k) for k in ("title", "subtitle", "paragraphs", "caption", "hashtags", "claims")}
        block += ("\n\n[이전 기사 — 처음부터 다시 쓰지 말고, 위 지적이 가리키는 부분만 고친다. 지적 없는 문단·문장·출처는 그대로 둔다]\n"
                  + json.dumps(keep, ensure_ascii=False))
    return block


def generate_article(llm: LLM, p: Profile, refs: str, cand: dict, research: str, *, best_own: str = "",
                     max_rounds: int = 3, seed_feedback: str = "", prev_article: dict | None = None,
                     progress=print) -> tuple[dict, dict]:
    """기사 생성 → 코드 검사 → 전문가 검수 → 미달이면 이전 기사+지적을 주고 그 부분만 고쳐 재검수. (기사, 검수결과) 반환.
    seed_feedback 이 있으면(다듬기) 첫 회부터 그 지적을 반영해 쓴다."""
    system, user = article_prompt(p, refs, cand, research, best_own)
    feedback = seed_feedback
    article: dict = dict(prev_article or {})
    verdict: dict = {}
    best: tuple[float, dict, dict] | None = None      # (점수, 기사, 검수) — 코드 검사는 통과한 것만
    for round_no in range(1, max_rounds + 1):
        prompt = user + _revise_block(article or None, feedback)
        article = llm.json(system=system, user=prompt, schema=ARTICLE_SCHEMA)
        problems = local_checks(p, article)
        es, eu = editor_prompt(p, article)
        verdict = llm.json(system=es, user=eu, schema=EDITOR_SCHEMA)
        if problems:
            verdict["verdict"] = "revise"
            verdict["feedback"] = "; ".join(problems) + " / " + str(verdict.get("feedback", ""))
        elif best is None or float(verdict.get("total") or 0) > best[0]:
            best = (float(verdict.get("total") or 0), article, verdict)
        progress(f"기사 {round_no}차: 검수 {verdict.get('total')}점 → {verdict.get('verdict')}")
        if verdict.get("verdict") == "pass":
            break
        feedback = str(verdict.get("feedback", ""))
    if verdict.get("verdict") != "pass" and best and best[0] >= p.pass_score:
        # 회차를 다 썼지만 기준 점수는 넘는 판이 있다 → 그 판을 채택하고 남은 지적은 메모로
        _, article, verdict = best
        verdict = {**verdict, "verdict": "pass", "note": f"{max_rounds}회 안에 검수관이 만족하지 않았지만 기준({p.pass_score}점)을 넘어 채택. 남은 지적은 feedback 참고"}
        progress(f"검수: 가장 높은 {best[0]}점 판 채택 (지적은 메모로)")
    if verdict.get("verdict") == "pass" and len(str(verdict.get("feedback", ""))) >= 200:
        # 통과했지만 검수관이 구체적인 손질 거리를 남겼다 → 한 번 다듬고, 점수가 안 떨어졌을 때만 채택
        article, verdict = _polish(llm, p, system, user, article, verdict, progress)
    return article, verdict


def _polish(llm: LLM, p: Profile, system: str, user: str, article: dict, verdict: dict, progress) -> tuple[dict, dict]:
    prompt = user + _revise_block(article, str(verdict.get("feedback", "")))
    try:
        polished = llm.json(system=system, user=prompt, schema=ARTICLE_SCHEMA)
        if local_checks(p, polished):
            progress("다듬기: 코드 검사 미달 → 원래 기사 유지")
            return article, verdict
        es, eu = editor_prompt(p, polished)
        v2 = llm.json(system=es, user=eu, schema=EDITOR_SCHEMA)
    except Exception as exc:  # noqa: BLE001
        progress(f"다듬기 실패({type(exc).__name__}) → 원래 기사 유지")
        return article, verdict
    progress(f"다듬기: 검수 {v2.get('total')}점 → {v2.get('verdict')}")
    if v2.get("verdict") == "pass" and float(v2.get("total") or 0) >= float(verdict.get("total") or 0):
        return polished, v2
    return article, verdict


# ───────────────────────── 4) 카드 요약 ─────────────────────────

def cards_prompt(p: Profile, article: dict, images_block: str) -> tuple[str, str]:
    system = (f"당신은 인스타그램 정보 계정 '{p.name}'의 카드뉴스 편집자입니다. 검수를 통과한 기사를 카드로 옮깁니다. "
              "카드 본문은 기사 문단을 **그대로** 쓰므로(코드가 문장 단위로 정렬) 당신은 표지 문구와 사진만 정합니다. "
              "도구를 쓰지 말고 JSON 만 출력합니다.\n"
              "규칙:\n"
              "- 표지(cover): title 은 기사 제목을 카드용으로 — 뜻이 끊기지 않는 자리에 줄바꿈 문자 \\n 을 넣어 2줄(한 줄 12자 안팎). sub 는 부제.\n"
              "- cover.category: 표지 분류 태그. 다음 중 하나: 'AI NEWS | TOOL', 'AI NEWS | UPDATE', 'AI TIPS | PROMPT', 'AI TIPS | IMAGE', 'AI TIPS | TEXT', 'AI TOOL | GENERAL'.\n"
              "- cards 는 문단 수와 같게, 문단 순서대로 한 항목씩. 각 항목: image_id(아래 후보 번호, 없으면 0), image_caption(사진이 무엇인지 한 줄), "
              "keyword(그 문단의 핵심어 하나 — 제품명·단축키·명령어·숫자. 예 'Alt+Space', '/autoprompt', '22초 vs 177초'. 카드 제목 아래 칩으로 표시됨), "
              "highlights(그 문단 text 안에 **글자 그대로 들어 있는** 강조할 어구 1~3개, 각 2~12자 — 색이 들어간다. 문단에 없는 말은 넣지 않는다).\n"
              "- 사진은 그 문단의 소주제와 **실제로 맞는** 것만 고른다(설명·출처로 판단). 공식 출처(official) 우선. 표지에는 가장 대표적인 화면·제품 사진. "
              "맞는 후보가 없으면 0 — 억지로 넣지 않는다.\n"
              f"- 마지막 카드 문구(cta): {p.cta}")
    user = ("기사:\n" + json.dumps({k: article.get(k) for k in ("title", "subtitle", "paragraphs")}, ensure_ascii=False, indent=1) +
            "\n\n사진 후보(번호·종류·설명·출처):\n" + (images_block or "(없음)") +
            '\n\nJSON: {"cover": {"title": "...\\n...", "sub": "...", "image_id": 0, "category": "AI NEWS | TOOL"}, '
            '"cards": [{"image_id": 0, "image_caption": "", "keyword": "...", "highlights": ["..."]}], "cta": "..."}')
    return system, user


def split_sentences(text: str) -> list[str]:
    """문단을 문장 단위로 나눈다(카드 한 줄 = 한 문장). 마침표·물음표·느낌표 뒤 공백에서 끊는다."""
    import re

    parts = re.split(r"(?<=[.?!。])\s+", str(text).strip())
    return [x.strip() for x in parts if x.strip()]


def local_card_checks(p: Profile, plan: dict, n_paragraphs: int, n_images: int) -> list[str]:
    problems = []
    cards = plan.get("cards", [])
    if len(cards) != n_paragraphs:
        problems.append(f"카드 {len(cards)}장 — 문단 수({n_paragraphs})와 같아야 함")
    for i, c in enumerate(cards, 1):
        iid = int(c.get("image_id") or 0)
        if iid < 0 or iid > n_images:
            problems.append(f"{i}번 카드 image_id {iid} 가 후보 범위 밖")
            c["image_id"] = 0
    cid = int(plan.get("cover", {}).get("image_id") or 0)
    if cid < 0 or cid > n_images:
        plan["cover"]["image_id"] = 0
    text = json.dumps(plan, ensure_ascii=False)
    for b in p.banned:
        if b and b in text:
            problems.append(f"금지 표현 '{b}' 포함")
    return problems


def plan_cards(llm: LLM, p: Profile, article: dict, images: list[dict], *, max_rounds: int = 2, progress=print) -> dict:
    """기사 → 카드 계획(표지 문구·사진 번호). 본문은 문단 그대로(문장 단위) 채우고, image_id 를 실제 후보(dict)로 바꿔 돌려준다."""
    from insta_research import as_prompt

    system, user = cards_prompt(p, article, as_prompt(images))
    by_id = {c["id"]: c for c in images}
    plan: dict = {}
    feedback = ""
    for round_no in range(1, max_rounds + 1):
        prompt = user + (f"\n\n[지적 — 반영해서 다시]\n{feedback}" if feedback else "")
        plan = llm.json(system=system, user=prompt, schema=CARDS_SCHEMA)
        problems = local_card_checks(p, plan, len(article.get("paragraphs", [])), len(images))
        progress(f"카드 계획 {round_no}차: " + ("OK" if not problems else "; ".join(problems)[:100]))
        if not problems:
            break
        feedback = "; ".join(problems)
    cover = plan.get("cover", {})
    cover["image"] = by_id.get(int(cover.get("image_id") or 0))
    if not cover["image"]:
        # 모델이 고른 사진이 없으면 원문·공식 페이지 캡처라도 표지에 넣는다 (글만 있는 표지는 스크롤을 못 세운다)
        shot = next((c for c in images if c.get("kind") == "screenshot"), None)
        if shot:
            cover["image"] = shot
            progress("표지 사진 없음 → 원문 페이지 캡처로 대체")
    paras = article.get("paragraphs", [])
    cards = plan.get("cards", [])
    # 본문은 기사 문단 그대로: 소제목 한 줄(줄바꿈 제거), 문장마다 한 줄
    for i, para in enumerate(paras):
        c = cards[i] if i < len(cards) else {"image_id": 0, "image_caption": ""}
        c["title"] = " ".join(str(para.get("heading", "")).split())
        c["lines"] = split_sentences(para.get("text", ""))
        text = str(para.get("text", ""))
        c["highlights"] = [h for h in (c.get("highlights") or []) if h and h in text][:3]
        c["keyword"] = " ".join(str(c.get("keyword") or "").split())[:24]
        c["image"] = by_id.get(int(c.get("image_id") or 0))
        if i >= len(cards):
            cards.append(c)
    plan["cards"] = cards[:len(paras)]
    return plan
