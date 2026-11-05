"""사회자 호명으로 자막을 위원별 구간으로 자른다 (순수 함수·상태 기계, 설계 5절).

자막에는 화자가 없다. "○○ 위원님 질의하여 주십시오" 같은 호명을 잡아 그 뒤 줄을 그 위원 몫으로 모은다.
- 호명은 두 줄로 갈려 오기도 해서(2026-11-05 실측) 최근 window_sec 안의 줄을 이어 붙인 글에 정규식을 건다.
- 구간이 닫히는 때: 다음 호명 · "○○ 위원님 수고하셨습니다" · 정회/산회 · 호명 없이 max_minutes 경과(flag "no_call").
- 첫 호명 전 줄(개회·안건 상정)은 어디에도 넣지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from captions import Caption

# 호명: 이름(2~4자) + 위원(님) + 질의/질문 + (하여|해) + 주시/주십/하겠/하십  — "존경하는 ○○ 위원님 말씀" 은 안 걸린다
CALL_RE = re.compile(r"([가-힣]{2,4})\s*위원님?\s*(질의|질문)\s*(하여|해)?\s*(주시|주십|하겠|하십)")
# 질의 종료 선언
END_RE = re.compile(r"([가-힣]{2,4})\s*위원님?\s*수고하셨")
# 정회·산회는 사회자의 선포 어미가 붙은 것만 — "산회 이후", "휴식 공간" 같은 발언 속 낱말에 걸리지 않게 (2026-11-05 재생 확인)
ADJOURN_RE = re.compile(r"산회를?\s*선포|산회하겠|산회합니다")
RECESS_RE = re.compile(r"정회를?\s*선포|정회하겠|정회하였다가|정회합니다|휴식을?\s*(하겠|취하|가지)")


@dataclass
class Segment:
    seq: int
    member: str
    party: str
    started_at: float
    ended_at: float | None = None
    lines: list[str] = field(default_factory=list)
    flag: str = ""        # "" | "no_call"(호명 없이 시간이 지나 닫힘)

    def text(self) -> str:
        return "\n".join(self.lines)


def detect_call(window_text: str, roster: set[str], special: str) -> str | None:
    """호명된 위원 이름. 명단(또는 special)에 있는 이름만 인정한다."""
    for m in CALL_RE.finditer(window_text or ""):
        name = m.group(1)
        if name == special or name in roster:
            return name
        if not roster:          # 명단을 아예 못 받은 날 — 가릴 수 없으니 호명 문장이면 받는다
            return name
        # "개혁신당 이준석" 처럼 앞 단어가 붙어 잡히면 뒤 2~4자를 다시 본다
        for n in range(2, 4):
            tail = name[-n:]
            if len(tail) >= 2 and (tail == special or tail in roster):
                return tail
    return None


def detect_close(text: str) -> str | None:
    """'done'(수고하셨습니다) · 'adjourn'(산회) · 'recess'(정회·휴식) · None."""
    t = text or ""
    if ADJOURN_RE.search(t):
        return "adjourn"
    if END_RE.search(t):
        return "done"
    if RECESS_RE.search(t):
        return "recess"
    return None


class Segmenter:
    def __init__(self, roster: dict[str, tuple[int, str]], special: str,
                 max_minutes: int = 25, window_sec: int = 10) -> None:
        self.roster = roster
        self.special = special
        self.max_sec = max_minutes * 60
        self.window_sec = window_sec
        self.current: Segment | None = None
        self._window: list[tuple[float, str]] = []
        self._used: set[int] = set()

    def restore(self, current: Segment | None, used: set[int]) -> None:
        """끊긴 실행이 저장해 둔 열린 구간·쓴 순번을 이어받는다."""
        self.current = current
        self._used = set(used)

    def next_seq(self, member: str) -> int:
        seq = self.roster.get(member, (0, ""))[0]
        if seq > 0 and seq not in self._used:
            return seq
        return max(self._used | {s for s, _ in self.roster.values()} | {0}) + 1

    def _close(self, at: float, flag: str = "") -> Segment:
        seg = self.current
        assert seg is not None
        seg.ended_at = at
        if flag:
            seg.flag = flag
        self.current = None
        return seg

    def _open(self, name: str, at: float) -> Segment:
        seq = self.next_seq(name)
        self._used.add(seq)
        self.current = Segment(seq, name, self.roster.get(name, (0, ""))[1], at)
        return self.current

    def feed(self, c: Caption) -> list[tuple]:
        events: list[tuple] = []
        # 호명 없이 너무 오래 열려 있으면 닫는다 — 이 줄은 누구 것인지 몰라 버린다
        if self.current and c.at - self.current.started_at > self.max_sec:
            events.append(("close", self._close(c.at, "no_call")))

        self._window = [(t, s) for t, s in self._window if c.at - t <= self.window_sec]
        self._window.append((c.at, c.text))
        window_text = " ".join(s for _, s in self._window)

        kind = detect_close(window_text)
        if kind:
            if self.current:
                events.append(("close", self._close(c.at)))
            if kind == "adjourn":
                self._window.clear()
                events.append(("adjourn",))
                return events
            # "○○ 위원님 수고하셨습니다 다음은 △△ 위원님 질의하여 주십시오" — 한 호흡에 오면 닫은 뒤 이어서 호명을 본다
            m = END_RE.search(window_text)
            window_text = window_text[m.end():] if m else ""
            self._window.clear()

        name = detect_call(window_text, set(self.roster), self.special)
        if name:
            if self.current:
                events.append(("close", self._close(c.at)))
            self._open(name, c.at)
            if name == self.special:
                events.append(("special_call", name))
            self._window.clear()
            return events

        if self.current and c.text.strip() and not kind:
            self.current.lines.append(c.text.strip())
        return events
