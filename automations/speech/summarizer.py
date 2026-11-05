"""위원 한 사람의 발언 구간을 주제별로 요약한다 (설계 6절, 모양은 사용자 확정 2026-11-05).

- summarize(): automations/common/llm.py 의 LLM(claude_cli → gemini) 호출. 예외는 밖으로(부르는 쪽이 failed_summary 로 대신한다).
- render_member(): 텔레그램에 들어갈 위원 한 명 블록 — "정당 이름" / "1. 주제" / "◯ 줄" …
"""
from __future__ import annotations

from dataclasses import dataclass, field

from segmenter import Segment

SYSTEM = """당신은 국회 의원실 보좌진을 위해 상임위·예결위 회의 발언을 정리하는 사람입니다.
주어진 글은 국회 생중계의 자막입니다. 오타·띄어쓰기 오류가 있고, 위원의 질의와 장관·기관장의 답변이 화자 구분 없이 섞여 있습니다. 사람 이름은 자막이 자주 틀리게 받아 적습니다.

위원이 다룬 주제마다 항목 하나를 만듭니다(보통 3~{topics_max}개). 짧게 지나간 주제도 빠뜨리지 않습니다.
- title: 주제를 명사구로 (예: "광역버스 준공영제 신설 노선 축소", "GTX-A 동탄 운행횟수 축소 우려").
- lines: 그 주제의 내용 2~3줄. 순서는 ① 위원이 지적한 사실과 근거 숫자·사례 ② 위원의 요구·제안 ③ 답변자의 답변. 각 줄은 한 문장, 70~120자, 어미는 "~했음"·"~답했음"·"~요구했음"처럼 "~음"으로 끝냅니다.
- 수치는 "17.5억 원", "1,500원", "약 5km"처럼 읽기 쉽게 다듬고, 지명·사업명은 자막 그대로 씁니다. 자막 오타는 명백한 것만 바로잡고 뜻을 바꾸지 않습니다. 자막 표기가 미심쩍으면 "(자막상 '…')"로 덧붙입니다.
- 번역투 없이 자연스러운 우리말로, 평가·논평 없이 사실만 씁니다.

답변자 가리기(중요):
- 위원이 "○○ 장관님", "총리님", "국세청 직무대행" 처럼 누구를 부른 뒤에 이어지는 답변은 그 사람의 것입니다. 부른 이름을 기준으로 답변자를 적습니다.
- 자막은 이름을 한 글자씩 틀리게 받아 적습니다(예: 박홍근→박홍문). 아래 출석자 명단과 가장 비슷한 이름으로 바로잡아 "이름 직책"(예: 홍지선 국토부장관)으로 적습니다. 명단에 없고 이름이 애매하면 직책만 씁니다.
- 오늘 출석자 명단: {attendees}

설명 없이 JSON 객체 하나만 출력하세요: {{"topics": [{{"title": "...", "lines": ["...", "..."]}}]}}"""


def schema_for(topics_max: int) -> dict:
    return {
        "type": "object", "required": ["topics"],
        "properties": {"topics": {
            "type": "array", "minItems": 1, "maxItems": topics_max,
            "items": {"type": "object", "required": ["title", "lines"],
                      "properties": {"title": {"type": "string"},
                                     "lines": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4}}}}},
    }


@dataclass
class MemberSummary:
    seq: int
    member: str
    party: str
    topics: list[dict] = field(default_factory=list)   # [{"title": str, "lines": [str, …]}]
    chars: int = 0
    failed: bool = False
    flag: str = ""        # Segment.flag 그대로 ("no_call" 이면 머리줄에 표시)


def load_attendees(path: str) -> list[str]:
    import yaml

    with open(path, encoding="utf-8") as fp:
        data = yaml.safe_load(fp) or {}
    return [str(a).strip() for a in (data.get("attendees") or []) if str(a).strip()]


def summarize(seg: Segment, meeting: str, attendees: list[str], llm, topics_max: int) -> MemberSummary:
    text = seg.text()
    system = SYSTEM.format(topics_max=topics_max, attendees=", ".join(attendees) or "(없음)")
    user = f"[회의: {meeting}]\n[위원: {seg.member}]\n\n{text}"
    data = llm.json(system=system, user=user, schema=schema_for(topics_max))
    topics = [{"title": str(t.get("title") or "").strip(), "lines": [str(x).strip() for x in (t.get("lines") or []) if str(x).strip()]}
              for t in (data.get("topics") or [])]
    return MemberSummary(seg.seq, seg.member, seg.party, topics, len(text), False, seg.flag)


def failed_summary(seg: Segment) -> MemberSummary:
    return MemberSummary(seg.seq, seg.member, seg.party, [], len(seg.text()), True, seg.flag)


def render_member(ms: MemberSummary) -> str:
    head = f"{ms.party} {ms.member}".strip()
    if ms.flag == "no_call":
        head += " (호명 못 잡음)"
    if ms.failed:
        return f"{head}\n요약 실패 — 발언 약 {ms.chars}자"
    lines = [head]
    for i, t in enumerate(ms.topics, 1):
        lines.append(f"{i}. {t['title']}")
        lines.extend(f"◯ {x}" for x in t["lines"])
    return "\n".join(lines)
