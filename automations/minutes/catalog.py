"""받아야 할 회의록 목록 생성."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator, Protocol

from record_site import CLASS_NAMES, Committee, Meeting, Session


@dataclass(frozen=True)
class MinutesEntry:
    id: int
    th: int
    cls: int
    committee: str
    sess: str          # 회기 번호 또는 국정감사 연도
    title: str
    temp: bool | None   # True 임시, False 확정, None 알 수 없음(Open API 출처)
    has_pdf: bool

    @property
    def class_name(self) -> str:
        return CLASS_NAMES[self.cls]


class SiteLike(Protocol):
    def committees(self, th: int, cls: int) -> list[Committee]: ...
    def sessions(self, th: int, cls: int, code: str) -> list[Session]: ...
    def meetings(self, th: int, cls: int, code: str, key: str) -> list[Meeting]: ...


def iter_entries(site: SiteLike, th: int, classes: Iterable[int], recent: int | None = None,
                 progress=None) -> Iterator[MinutesEntry]:
    """대수 th의 회의구분 classes를 돌며 회의록 항목을 낸다.

    recent가 주어지면 위원회마다 최신 회기(또는 연도) recent개만 본다.
    사이트는 회기를 최신순으로 주므로 앞에서 자른다.
    """
    def say(msg: str) -> None:
        if progress:
            progress(msg)

    for cls in classes:
        for c in site.committees(th, cls):
            sessions = site.sessions(th, cls, c.code)
            if recent is not None:
                sessions = sessions[:recent]
            say(f"제{th}대 {CLASS_NAMES[cls]} {c.name}: 회기 {len(sessions)}개")
            for s in sessions:
                for m in site.meetings(th, cls, c.code, s.key):
                    yield MinutesEntry(
                        id=m.id, th=th, cls=cls, committee=c.name, sess=s.key,
                        title=m.title, temp=m.temp, has_pdf=m.has_pdf,
                    )


def iter_temp_recheck(site: SiteLike, th: int, pending: Iterable[dict],
                      progress=None) -> Iterator[MinutesEntry]:
    """임시회의록으로 기록된 항목(manifest 행)의 회기를 사이트에서 다시 읽어 확정 여부를 낸다.

    pending 행은 th, cls, committee, sess 키를 가진다. 같은 (cls, committee, sess)는 한 번만 조회한다.
    """
    def say(msg: str) -> None:
        if progress:
            progress(msg)

    groups: dict[tuple[int, str], set[str]] = {}
    for row in pending:
        if row.get("sess"):
            groups.setdefault((int(row["cls"]), row["committee"]), set()).add(str(row["sess"]))

    codes_cache: dict[int, dict[str, str]] = {}
    for (cls, committee), sessions in sorted(groups.items()):
        if cls not in codes_cache:
            codes_cache[cls] = {c.name: c.code for c in site.committees(th, cls)}
        code = codes_cache[cls].get(committee)
        if code is None:
            say(f"임시 재확인 건너뜀: 제{th}대 {CLASS_NAMES[cls]} {committee} (위원회 코드 없음)")
            continue
        for sess in sorted(sessions):
            say(f"임시 재확인: 제{th}대 {CLASS_NAMES[cls]} {committee} 제{sess}회")
            for m in site.meetings(th, cls, code, sess):
                yield MinutesEntry(
                    id=m.id, th=th, cls=cls, committee=committee, sess=sess,
                    title=m.title, temp=m.temp, has_pdf=m.has_pdf,
                )
