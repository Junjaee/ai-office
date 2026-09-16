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
import re
from dataclasses import dataclass, replace

from insta_llm import LLM

QUERY_SCHEMA = {
    "type": "object", "required": ["queries"],
    "properties": {"queries": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "string", "maxLength": 60}}},
}

PICK_SCHEMA = {
    "type": "object",
    "required": ["picks"],
    "properties": {"picks": {"type": "array", "minItems": 1, "maxItems": 20,
                             "items": {"type": "object", "required": ["index", "reason", "angle"],
                                       "properties": {"index": {"type": "integer"}, "reason": {"type": "string"},
                                                      "angle": {"type": "string"}, "title_ko": {"type": "string", "maxLength": 40},
                                                      "gap": {"type": "boolean"}}}}},
}

ARTICLE_SCHEMA = {
    "type": "object",
    "required": ["title", "subtitle", "paragraphs", "caption", "hashtags", "alt_text", "sources", "claims", "dm_keyword", "dm_text"],
    "properties": {
        "title": {"type": "string", "minLength": 6, "maxLength": 40},
        "dm_keyword": {"type": "string", "minLength": 1, "maxLength": 12},
        "dm_text": {"type": "string", "minLength": 60, "maxLength": 950},
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

# 한글 채팅 화면 목업(우리가 그리는 그래픽): 앱 이름, 사용자 입력, 답변 줄(표는 "|" 로 칸 구분)
MOCK_SCHEMA = {
    "type": "object", "required": ["user", "assistant"],
    "properties": {"app": {"type": "string", "maxLength": 20},
                   "user": {"type": "string", "maxLength": 120},
                   "assistant": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "string", "maxLength": 60}}},
}

CARDS_SCHEMA = {
    "type": "object",
    "required": ["cover", "cards", "cta"],
    "properties": {
        "cover": {"type": "object", "required": ["title", "sub"],
                  "properties": {"title": {"type": "string", "maxLength": 48}, "sub": {"type": "string", "maxLength": 80},
                                 "image_id": {"type": "integer"}, "category": {"type": "string", "maxLength": 24},
                                 "image_query": {"type": "string", "maxLength": 60}, "mock": MOCK_SCHEMA}},
        "cards": {
            "type": "array", "minItems": 1, "maxItems": 9,
            "items": {"type": "object", "required": ["image_id"],
                      "properties": {"image_id": {"type": "integer"},
                                     "image_caption": {"type": "string", "maxLength": 60},
                                     "keyword": {"type": "string", "maxLength": 24},
                                     "highlights": {"type": "array", "maxItems": 3, "items": {"type": "string", "maxLength": 30}},
                                     "image_query": {"type": "string", "maxLength": 60}, "mock": MOCK_SCHEMA}},
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
    watch_accounts: list[str] | None = None   # 참고할 한국 AI 인스타 계정(프로페셔널) — 최근 게시물이 후보 앞자리
    watch_foreign: list[str] | None = None    # 미국 원출처 인스타(회사 공식·Rundown 등) — 최근 48시간 게시물, 한국이 아직 안 다룬 것은 빈자리
    watch_foreign_hours: int = 48
    watch_cap: int = 15                       # 참고 계정 그룹별 후보 상한(좋아요 순)
    watch_per_account: int = 4                # 계정당 후보 상한 (좋아요 많은 계정이 독식하지 않게)
    pick_rules: str = ""                      # 주제별 편집장 선정 기준(있으면 AI 계정용 기본 기준 대신 쓴다)
    signal_required: list[str] | None = None  # 이 출처들은 신호 단어가 있는 글만 후보로 (연합뉴스처럼 넓은 피드)
    exclude_words: list[str] | None = None    # 제목에 이 말이 있으면 후보에서 뺀다 (인사·부고·군 단위 소식 등)
    tts_voice: str = ""                       # 나레이션 릴스 목소리 (기본 ko-KR-SunHiNeural, 남성 ko-KR-InJoonNeural)
    brand: str = ""                           # 카드·릴스 위 브랜드 라벨 (없으면 'AI TIPS')
    source_caps: dict | None = None            # 출처별 후보 상한 {출처이름: N} (레딧처럼 시끄러운 곳 제한)
    title_patterns: list[str] | None = None
    cc_photos: bool = False             # True 면 사진 없는 카드에 CC 사진(Openverse)을 검색해 넣는다 — 관련 없는 사진이 걸릴 수 있어 기본 끔
    slides: int = 0                     # (구버전 호환) 쓰지 않음
    hook_patterns: list[str] | None = None
    flow: dict | None = None
    images_per_post: int = 0
    reel: bool = False                  # True 면 릴스(영상) 캡션·자막용 짧은 기사 규칙 (reel_profile 이 켠다)

    @classmethod
    def from_dict(cls, d: dict) -> "Profile":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


def _video_source(url: str) -> bool:
    return bool(re.search(r"(youtube\.com/|youtu\.be/|(?:x|twitter)\.com/\w+/status/)", url or ""))


def reel_profile(p: Profile) -> Profile:
    """영상 소재용 프로필: 문단 4개, 합격선 6점 완화, 릴스 규칙 켬. (유튜브 설명·X 글처럼 근거가 짧아도 쓸 수 있게)"""
    return replace(p, paragraphs=4, pass_score=max(30, int(p.pass_score) - 6), reel=True)


# ───────────────────────── 1) 소재 고르기 / 검색어 ─────────────────────────

SHARE_RULE = ("**보내고 태그할 거리에 가점**(2026-09-15 사용자 판단): 서로 태그하거나 DM으로 보내며 지적·놀리는 놀이가 되는 주제가 잘 퍼진다 "
              "(예: 아내가 남편에게 '애 앞에서 폰 좀 그만' 하며 보내는 영상). '이걸 누구에게 보낼까?'(배우자·동료·팀장·친구·부모님)가 바로 떠오르는 소재를 앞에 두고, "
              "angle 에 보낼 상대를 적는다. 깎아내리는 조롱거리는 고르지 않는다.")

def pick_prompt(p: Profile, rows: str, n: int) -> tuple[str, str]:
    if p.pick_rules:
        system = (f"당신은 인스타그램 정보 계정 '{p.name}'의 편집장입니다. 독자: {p.audience}\n"
                  "후보 목록에서 오늘 게시할 소재를 고릅니다. 선정 기준: 독자가 바로 써먹을 수 있는가, 저장·공유하고 싶은가, 새로운가, "
                  "기사 한 편(문단 5~7개)으로 풀 수 있는가. 광고·모금·행사 안내·기업 실적 뉴스, '#광고'·'제작지원'이 붙은 게시물은 제외.\n"
                  "**남의 영상 자체가 핵심인 소재는 고르지 않는다**(바이럴 릴스·뮤비·'N만 명이 봤다'·영상 반응 이야기 — 우리는 그 영상을 보여 줄 수 없어 빈 화면에 말만 남는다, 2026-09-15 사용자 지적). 영상이 꼭 필요한 소재는 [🎬영상] 표시(받을 수 있는 공식 유튜브·X 영상)가 있을 때만.\n"
                  f"{SHARE_RULE}\n"
                  f"{p.pick_rules.strip()}\n"
                  "[🎬영상] 표시(공식 유튜브·X 영상)는 릴스로 만들 수 있어 반응이 좋다. 같은 소식을 여러 매체가 다뤘으면 가장 공식적인 출처 하나만 고른다.\n"
                  "도구를 쓰지 말고 JSON 객체 하나만 출력합니다.")
        user = (f"후보:\n{rows}\n\n"
                f"가장 좋은 {n}개를 고르고(좋은 순서대로, 서로 다른 주제로) 각각 index(후보 번호), title_ko(한국어 제목 한 줄, 20자 안팎 — 검토하는 사람이 한눈에 알게), "
                "reason(선정 이유 한 줄 — 독자에게 왜 도움이 되는지), angle(기사로 풀 때의 각도 한 줄), gap(false)을 적으세요.\n"
                'JSON: {"picks": [{"index": 3, "title_ko": "...", "reason": "...", "angle": "...", "gap": false}]}')
        return system, user
    system = (f"당신은 인스타그램 정보 계정 '{p.name}'의 편집장입니다. 독자: {p.audience}\n"
              "후보 목록에서 오늘 게시할 소재를 고릅니다. 선정 기준: 독자가 바로 써먹을 수 있는가, 저장하고 싶은가, 새로운가, "
              "기사 한 편(문단 5~7개)으로 풀 수 있는가. 광고·모금·행사 안내·기업 실적 뉴스, '#광고'·'제작지원'이 붙은 게시물은 제외.\n"
                  "**남의 영상 자체가 핵심인 소재는 고르지 않는다**(바이럴 릴스·뮤비·'N만 명이 봤다'·영상 반응 이야기 — 우리는 그 영상을 보여 줄 수 없어 빈 화면에 말만 남는다, 2026-09-15 사용자 지적). 영상이 꼭 필요한 소재는 [🎬영상] 표시(받을 수 있는 공식 유튜브·X 영상)가 있을 때만.\n"
                  f"{SHARE_RULE}\n"
              "**최우선 기준은 대중성이다(사용자 위임 2026-09-14 — 목표는 팔로워·조회수)**: 직장인·학생이 '오늘 바로 따라 해 보고 싶다'고 느끼는 것 — 프롬프트 한 줄로 되는 결과물(사진→그림, 배경화면, 영상), "
              "무료 혜택·꿀기능·단축키, 신기한 데모, 돈·시간 아끼는 활용법. 반대로 기업용·개발자용 소식(API, 금융·엔터프라이즈 제품, 투자·실적, 인사)은 아주 크지 않으면 고르지 않는다. "
              "한국 AI 계정에서 좋아요·댓글이 많았던 유형이 대중성의 증거다. 1번은 자동 게시되므로 가장 대중적인 것으로.\n"
              "그 다음 우선순위(2026-09-12): ① **미국 원출처에서 최근 24시간 안에 나온 새 소식** — OpenAI·Google DeepMind·Anthropic·The Rundown·TestingCatalog 같은 공식·해외 RSS 와 "
              "'IG 🇺🇸 @계정' 게시물. 한국 계정('IG 🇰🇷 @계정')이 아직 다루지 않은 주제면 gap=true(빈자리)로 표시한다 — 우리가 한국에 제일 먼저 올리는 셈이라 가장 귀하다. "
              "② **한국 AI 인스타에서 반응이 좋았던 주제**(좋아요·댓글 많은 것) — 같은 주제를 그대로 골라도 된다(피할 필요 없음). 우리는 우리 식(기사→카드, 우리가 그린 화면)으로 다시 쓴다. "
              "③ 그 외 RSS·커뮤니티 글은 공식 링크가 있을 때만 맨 뒤. 고른 것 중 ①을 절반 이상, 나머지는 ②에서 고른다. 사용자가 고르지 않으면 1순위가 07:30 에 자동 게시되므로 1번은 가장 확실한 것으로. "
              "[🎬영상] 표시(공식 유튜브·X 영상)는 릴스로 만들 수 있어 반응이 좋으니 4~5개는 영상이 있는 것으로.\n"
              "도구를 쓰지 말고 JSON 객체 하나만 출력합니다.")
    user = (f"후보:\n{rows}\n\n"
            f"가장 좋은 {n}개를 고르고(좋은 순서대로, 서로 다른 주제로) 각각 index(후보 번호), title_ko(한국어 제목 한 줄, 20자 안팎 — 검토하는 사람이 한눈에 알게), "
            "reason(선정 이유 한 줄 — 독자에게 왜 도움이 되는지), angle(기사로 풀 때의 각도 한 줄), gap(미국 소식인데 한국 계정에 아직 없으면 true)을 적으세요.\n"
            'JSON: {"picks": [{"index": 3, "title_ko": "...", "reason": "...", "angle": "...", "gap": false}]}')
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
        f"- 제목(title): **엄지를 멈추게 하는 제목**이 이 글의 절반이다. 사실을 벗어난 낚시는 금지지만, 밋밋한 요약 제목('~출시', '~업데이트')은 실패다. "
        "반드시 다음 중 하나를 쓴다: ① 숫자+대비('프롬프트 3개로 내 정보 싹 지웠어요', '22초 vs 177초') ② 독자에게 직접 말 걸기('여러분, 지금 당장 카톡 켜세요', '아직 이거 손으로 하세요?') "
        "③ 손해·놓침 자극('나만 몰랐던', '모르면 한 달 손해') ④ 결과 먼저('사진 한 장이 그림이 됐어요') ⑤ 반전·의문('AI한테 마우스를 넘겨준 첫날 풍경'). "
        f"구체적인 명사·숫자가 들어가야 하고 '혁신'·'주목'·'화제' 같은 빈말은 금지. 패턴 예: {' / '.join(pats)}. 20자 안팎(표지에 두 줄).",
        "- 본문에 인상적인 **숫자·대비**(예: 22초 vs 177초, 8배, 무료, 하루 100장)가 있으면 제목이나 부제에 반드시 끌어온다. '완결편'·'총정리' 같은 밋밋한 말에만 기대지 않는다.",
        "- **번역투·보고서 말투 금지**(2026-09-16, 육아 계정에서 배운 것을 AI 계정에도): 영어 자료를 옮길 때 '관련이 있었다·연관됐다'는 '~할수록 ~했다'로 풀고, '~는 다른 이야기를 한다'·'~ 자신의'·'~ 단위로 봐야' 같은 직역과 '~로 나타났습니다'·'~가 확인되었습니다' 같은 자료 문장을 쓰지 않는다. 다 쓰고 한 문장씩 소리 내어 읽어 어색한 곳을 고친다. 내용·숫자는 바꾸지 않는다.",
        "- 부제(subtitle): 제목이 약속한 이득을 한 줄로.",
        f"- 문단(paragraphs) {p.paragraphs}개. **문단 하나 = 소주제 하나**. heading 은 그 소주제를 12자 안팎으로, text 는 3~4줄(90~200자) 완결된 문장.",
        "- 문단 순서: 독자가 궁금한 순서. 소식이면 '언제·누가·무엇 → 달라지는 점(장점) 여러 개 → 쓰는 법 → 받는 곳·조건' 순.",
        "- 문단마다 구체적인 예(숫자·화면·입력 예시)를 하나 이상 넣는다. 추상적인 설명만 있는 문단은 실패.",
        f"- 반드시 포함: {', '.join(p.must_include)}" + ("" if not p.reel else " (영상 글에서는 확인되는 것만 — 없으면 빼도 감점 아님)"),
        *(["- **이 글은 릴스(세로 영상)의 캡션·자막용**이다. 영상이 보여 주는 것(무엇을, 어떻게, 결과가 어땠는지)을 문단 4개로 쓴다. "
           "영상 설명·원문에 있는 사실만 쓰고, 요금·지원 기기·날짜처럼 확인 안 되는 세부와 '업계 반응'·'전문가 평가' 같은 원문에 없는 내용은 넣지 않는다. "
           "claims 의 source 는 그 영상 주소(유튜브·X)여도 된다. 제목은 영상 위에 크게 얹히므로 18자 안, 부제는 한 줄. "
           "caption 은 영상 아래 본문이므로 첫 줄에 제목, 둘째 문단에 영상 설명, 셋째에 저장·공유 유도(보낼 상대를 콕 집어: '배우자에게 꼭 보내 주세요', '아직 손으로 하는 동료 태그')."] if p.reel else []),
        f"- 금지 표현: {', '.join(p.banned)}. 느낌표 남발·이모지 금지(캡션은 문단당 1개 이하).",
        "- 숫자·툴 이름·명령어는 출처 그대로. 소재 원문·공식 링크·관련 글에 없는 사실은 쓰지 않는다. 확실치 않은 세부(요금·지원 OS·날짜)는 '공식 안내 확인' 으로 돌린다.",
        "- 모든 사실 주장은 claims 에 {text, source(URL)} 로 넣는다(공식 출처 우선). **인스타그램·스레드 등 SNS 게시물 주소는 출처로 쓸 수 없다** — "
        "소재가 다른 계정의 인스타 글이면 그 글은 '이런 주제가 반응이 좋았다'는 힌트일 뿐이고, 사실은 아래 관련 글·공식 페이지에서 찾아 그 주소를 단다. 못 찾은 세부는 쓰지 않는다.",
        "- 남의 글을 옮겨 쓰지 않는다: 참고 계정 글의 문장·표현을 그대로 쓰거나, 그 계정의 체험('실제로 돌려봤더니', '~해 봤어요')을 우리 체험처럼 쓰지 않는다. 우리가 직접 한 것이 아니면 '~할 수 있어요', '~된다고 해요' 로 쓴다.",
        "- caption: 인스타 본문. 300~500자, 3문단(첫 줄 = 제목 반복 → 핵심 요약 → 저장·공유 유도 — 보낼 상대를 콕 집어 '○○에게 보내 주세요'·'○○ 태그' 한 줄).해시태그는 hashtags 배열로. "
        "마지막 줄은 반드시 댓글 유도: \"💬 댓글에 '<dm_keyword>' 라고 남기면 <무엇>을 DM 으로 보내드려요\" (다른 AI 계정들이 전부 쓰는 방식 — 댓글이 3~10배 늘어 노출이 커진다).",
        "- dm_keyword: 댓글로 남길 짧은 한글 말(2~6자, 예 '프롬프트', '지우기', '레시피'). 글 주제와 이어지는 말.",
        "- dm_text: 댓글 단 사람에게 DM 으로 보낼 **실제 쓸모 있는 것** — 이 글의 프롬프트 전문(복붙해서 바로 쓰는 문장 1~3개), 없으면 따라 하는 순서 5줄. "
        "인사 한 줄 → 내용 → '저장해 두고 써 보세요' 한 줄. 950자 안. 링크·해시태그 없음. 원문에 없는 기능을 지어내지 않는다.",
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
    from insta_research import is_social

    for c in article.get("claims", []):
        src = str(c.get("source", ""))
        if not src.startswith("http"):
            problems.append(f"출처가 URL 이 아님: {c.get('source')}")
            break
        if is_social(src) and not (p.reel and _video_source(src)):
            # 릴스(영상) 글은 그 영상(유튜브·X)이 곧 원문이라 출처로 허용한다 (사용자 결정 2026-09-12: 남의 영상은 출처 표기하고 사용)
            problems.append(f"SNS 게시물은 출처로 쓸 수 없음 — 공식 페이지·기사 주소로: {src[:50]}")
            break
    text_all = " ".join(str(x.get("text", "")) for x in article.get("paragraphs", []))
    if re.search(r"(실제로 )?(돌려|해|써|넣어|시켜)\s*봤(더니|어요|습니다|는데)", text_all):
        problems.append("남의 체험담을 우리 체험처럼 씀('~해 봤더니') — '~할 수 있어요'/'~된다고 해요' 로")
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
    # 댓글 유도 줄: 키워드가 캡션에 없으면 마지막에 붙인다 (모델이 빠뜨려도 게시 규칙은 지킨다)
    kw = str(article.get("dm_keyword") or "").strip().strip("'\"")
    article["dm_keyword"] = kw
    if kw and article.get("dm_text") and kw not in str(article.get("caption", "")):
        article["caption"] = str(article.get("caption", "")).rstrip() + f"\n\n💬 댓글에 '{kw}' 라고 남기면 이 글의 프롬프트를 DM 으로 보내드려요"
    if article.get("dm_text") and len(str(article["dm_text"])) < 60:
        problems.append("dm_text 가 너무 짧음 — 프롬프트 전문이나 따라 하는 순서를 60자 이상으로")
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
              "맞는 후보가 없으면 0. **다른 인스타 계정의 게시물 사진·화면은 후보에 없고 절대 쓰지 않는다** — 그 대신 같은 내용을 보여 줄 사진을 image_query 로 찾는다.\n"
              "- mock(한글 화면 목업): 사진 후보에 **한글 화면**이 없으면 표지(cover.mock)와 사진 없는 카드에 챗GPT·제미나이 같은 앱 화면을 한글로 구성한다 — "
              "app(앱 이름), user(그 카드 내용을 보여 주는 한국어 입력 한 줄), assistant(한국어 답변 3~5줄. 표가 어울리면 '사이트 | 노출 정보 | 삭제 링크' 처럼 '|' 로 칸을 나눈다). "
              "실제 결과처럼 보이되 지어낸 회사명·개인정보는 넣지 않는다(예: '사람찾기 사이트 A'). 영어 화면·영어 문장 금지.\n"
              "- image_query: 후보 중 맞는 게 없을 때(또는 후보가 없을 때) 그 카드에 어울리는 **개념 사진**을 찾을 영어 검색어 2~5단어 "
              "(예 'person typing laptop privacy', 'smartphone photo gallery', 'security padlock data'). CC 라이선스 사진 저장소에서 찾으므로 제품 화면이 아니라 상황·사물 사진을 뜻하는 말로. "
              "표지에도 cover.image_query 를 반드시 채운다.\n"
              f"- 마지막 카드 문구(cta): {p.cta}")
    user = ("기사:\n" + json.dumps({k: article.get(k) for k in ("title", "subtitle", "paragraphs")}, ensure_ascii=False, indent=1) +
            "\n\n사진 후보(번호·종류·설명·출처):\n" + (images_block or "(없음)") +
            '\n\nJSON: {"cover": {"title": "...\\n...", "sub": "...", "image_id": 0, "category": "AI NEWS | TOOL", "image_query": "...", '
            '"mock": {"app": "ChatGPT", "user": "...", "assistant": ["...", "..."]}}, '
            '"cards": [{"image_id": 0, "image_caption": "", "keyword": "...", "highlights": ["..."], "image_query": "...", "mock": {...}}], "cta": "..."}')
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
    used: set[str] = set()
    if not cover["image"]:
        # 모델이 고른 사진이 없으면 CC 사진(image_query) → 공식 페이지 캡처 순으로 표지를 채운다 (글만 있는 표지는 스크롤을 못 세운다)
        shot = next((c for c in images if c.get("kind") == "screenshot"), None)
        photo = next((c for c in images if c.get("kind") in ("official", "related")), None)
        cc = cc_search(cover.get("image_query", ""), used) if p.cc_photos else None
        # 공식 페이지 캡처 → (한글 목업이 있으면 목업) → 기사 사진 → (옵션) CC. 사진이 없으면 목업만 그린다
        cover["image"] = shot or (None if cover.get("mock") else (photo or cc))
        if cover["image"]:
            progress("표지 사진 없음 → " + {"screenshot": "공식 페이지 캡처", "cc": "CC 사진"}.get(cover["image"].get("kind", ""), "기사 사진") + "으로 대체")
    if cover["image"]:
        used.add(cover["image"]["url"])
    # 표지 사진이 렌더 때 실패(차단·빈 화면)하면 쓸 예비 후보: 사진 → 다른 캡처 순
    cover["fallbacks"] = [c for c in images if c.get("kind") in ("official", "related", "screenshot")
                          and c is not cover["image"] and c["url"] not in used][:4]
    cover["mock"] = clean_mock(cover.get("mock"))
    paras = article.get("paragraphs", [])
    cards = plan.get("cards", [])
    # 본문은 기사 문단 그대로: 소제목 한 줄(줄바꿈 제거), 문장마다 한 줄
    for i, para in enumerate(paras):
        c = cards[i] if i < len(cards) else {"image_id": 0, "image_caption": ""}
        c["title"] = " ".join(str(para.get("heading", "")).split())
        text = str(para.get("text", ""))
        c["prompt"] = extract_prompt(text)          # 따옴표 안 입력 문장 → 채팅 말풍선 그래픽 (우리 것)
        body_text = strip_prompt(text, c["prompt"]) if c["prompt"] else text
        c["lines"] = split_sentences(body_text)
        c["highlights"] = [h for h in (c.get("highlights") or []) if h and h in text][:3]
        c["keyword"] = " ".join(str(c.get("keyword") or "").split())[:24]
        c["image"] = by_id.get(int(c.get("image_id") or 0))
        if c["image"] and c["image"]["url"] in used:
            c["image"] = None                       # 같은 사진을 두 카드에 쓰지 않는다
        c["mock"] = clean_mock(c.get("mock")) if not c["image"] and i < 4 else None   # 사진 없는 앞 카드만 목업
        if c["prompt"]:
            c["image"] = None                       # 말풍선이 있는 카드는 사진을 겹치지 않는다
            c["mock"] = None                        # 말풍선과 목업을 같이 두지 않는다
        if not c["image"] and not c["prompt"] and i < 4 and p.cc_photos:
            c["image"] = cc_search(c.get("image_query", ""), used)
            if c["image"]:
                c["image_caption"] = c.get("image_caption") or c["image"].get("alt", "")
        if c["image"]:
            used.add(c["image"]["url"])
        if i >= len(cards):
            cards.append(c)
    plan["cards"] = cards[:len(paras)]
    return plan


def extract_prompt(text: str) -> str:
    """문단 안 따옴표('…' / "…" / ‘…’ / “…”)로 감싼 입력 문장(15자 이상, 해 줘/해줘/해주세요 꼴)을 하나 꺼낸다. 없으면 빈 문자열."""
    for m in re.finditer(r"[\'‘\"“]([^\'’\"”]{15,200})[\'’\"”]", text or ""):
        cand = m.group(1).strip()
        if re.search(r"(해\s?줘|해주세요|해 주세요|정리해|찾아|알려|보내|만들어|바꿔|써 줘|써줘)", cand):
            return cand
    return ""


def clean_mock(m) -> dict | None:
    """목업 검사: 사용자 입력·답변이 한국어인지, 영어 문장은 버린다."""
    if not isinstance(m, dict) or not m.get("user") or not m.get("assistant"):
        return None
    lines = [str(x).strip() for x in m.get("assistant", []) if str(x).strip()][:6]
    if not lines or not re.search(r"[가-힣]", str(m["user"])) or not any(re.search(r"[가-힣]", ln) for ln in lines):
        return None
    return {"app": str(m.get("app") or "ChatGPT")[:20], "user": str(m["user"])[:120], "assistant": lines}


def strip_prompt(text: str, prompt: str) -> str:
    """문단에서 따옴표로 감싼 프롬프트를 통째로 뺀다(말풍선으로 옮겼으니 본문에서 중복되지 않게)."""
    out = re.sub(r"[\'‘\"“]\s*" + re.escape(prompt) + r"\s*[\'’\"”]\s*(라고|처럼|같이)?\s*", " ", text or "")
    return re.sub(r"\s{2,}", " ", out).strip()


def cc_search(query: str, used: set[str]) -> dict | None:
    """image_query 로 CC 사진을 찾아 아직 안 쓴 첫 장을 돌려준다. 검색 실패·없음이면 None."""
    from insta_research import openverse_search

    words = (query or "").split()
    # 검색어가 길면 결과가 0건이기 쉬우니 뒤에서부터 한 단어씩 줄여 가며 찾는다 (최소 2단어)
    while len(words) >= 2:
        for c in openverse_search(" ".join(words), n=6):
            if c["url"] not in used:
                return c
        words = words[:-1]
    return None
