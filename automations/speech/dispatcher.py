"""요약이 끝난 위원을 묶어 보낼 차례를 정하고(설계 7절), 텔레그램 메시지 글을 만든다. 순수 함수.

규칙(사용자 결정 2026-11-05):
1. 준비 큐에 batch_size(10)명이 모이면 한 묶음.
2. 이준석 위원이 호명되면 준비 큐를 그 자리에서 보낸다(10명 미만이어도).
3. 이준석 위원 요약은 단독 메시지. 그 뒤 큐에 남은 것(요약이 늦었던 앞 사람)은 "뒤늦게"로 따로.
4. 회의가 끝나면 남은 것 전부.
메시지는 4,096자를 넘으면 위원 경계에서 나누고 머리줄에 (i/n) 을 붙인다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from summarizer import MemberSummary, render_member

TELEGRAM_LIMIT = 4096


@dataclass
class Batch:
    kind: str                           # "batch" | "special" | "late"
    items: list[MemberSummary] = field(default_factory=list)

    def seqs(self) -> list[int]:
        return [m.seq for m in self.items]


class Dispatcher:
    def __init__(self, batch_size: int, special: str, already_sent: set[int] | frozenset[int] = frozenset()) -> None:
        self.batch_size = batch_size
        self.special = special
        self.already_sent = set(already_sent)
        self.queue: list[MemberSummary] = []
        self.last_special_seq = 0

    def _take_queue(self, kind: str) -> list[Batch]:
        if not self.queue:
            return []
        items = sorted(self.queue, key=lambda m: m.seq)
        self.queue = []
        return [Batch(kind, items)]

    def ready(self, ms: MemberSummary) -> list[Batch]:
        if ms.seq in self.already_sent:
            return []
        if ms.member == self.special:
            self.last_special_seq = max(self.last_special_seq, ms.seq)
            return [Batch("special", [ms])] + self._take_queue("late")
        if ms.seq < self.last_special_seq:
            return [Batch("late", [ms])]
        self.queue.append(ms)
        if len(self.queue) >= self.batch_size:
            return self._take_queue("batch")
        return []

    def special_called(self) -> list[Batch]:
        """이준석 위원 호명 — 준비된 것은 지금 보낸다."""
        return self._take_queue("batch")

    def flush(self) -> list[Batch]:
        return self._take_queue("batch")


def _header(b: Batch, meeting: str) -> str:
    seqs = b.seqs()
    if b.kind == "special":
        m = b.items[0]
        return f"🔵 {m.party} {m.member}".rstrip() + f" · 질의 {m.seq}"
    if b.kind == "late":
        return f"📋 {meeting} · 질의 {seqs[0]} (뒤늦게)"
    rng = f"{seqs[0]}" if seqs[0] == seqs[-1] else f"{seqs[0]}~{seqs[-1]}"
    return f"📋 {meeting} · 질의 {rng}"


def _hard_split(block: str, room: int) -> list[str]:
    """위원 한 명 블록이 혼자 한도를 넘을 때 줄 단위로 자른다."""
    parts: list[str] = []
    cur = ""
    for line in block.split("\n"):
        cand = line if not cur else cur + "\n" + line
        if len(cand) > room and cur:
            parts.append(cur)
            cur = line
        else:
            cur = cand
    if cur:
        parts.append(cur)
    return parts


def render_messages(b: Batch, meeting: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    head = _header(b, meeting)
    room = limit - len(head) - len(" (99/99)") - 2
    blocks = [render_member(m) for m in b.items]
    chunks: list[str] = []
    cur = ""
    for block in blocks:
        pieces = [block] if len(block) <= room else _hard_split(block, room)
        for piece in pieces:
            cand = piece if not cur else cur + "\n\n" + piece
            if len(cand) > room and cur:
                chunks.append(cur)
                cur = piece
            else:
                cur = cand
    if cur:
        chunks.append(cur)
    if len(chunks) <= 1:
        return [f"{head}\n\n{chunks[0] if chunks else ''}".rstrip()]
    n = len(chunks)
    return [f"{head} ({i}/{n})\n\n{c}" for i, c in enumerate(chunks, 1)]
