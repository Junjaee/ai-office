"""실행 중 상태를 Worker(/api/speech/state, R2)에 저장·복원한다 (설계 8절).

6시간 한도로 실행이 끊겨도 다음 실행이 보낸 묶음·열린 구간을 이어 받는다. 저장 실패는 예외로 던지고,
부르는 쪽이 오류 종류만 로그에 남기고 계속 간다 — 상태 저장 때문에 회의를 놓치지 않게.
"""
from __future__ import annotations

from dataclasses import asdict

from segmenter import Segment

STATE_VERSION = 1


class StateClient:
    def __init__(self, base_url: str, token: str = "", session=None, timeout: int = 20) -> None:
        import requests

        self.base = base_url.rstrip("/")
        self.headers = {"X-Live-Token": token} if token else {}
        self.s = session or requests.Session()
        self.timeout = timeout

    def get(self, key: str) -> dict | None:
        res = self.s.get(f"{self.base}/api/speech/state", params={"key": key}, headers=self.headers, timeout=self.timeout)
        if res.status_code == 404:
            return None
        res.raise_for_status()
        return res.json()

    def put(self, key: str, data: dict) -> None:
        res = self.s.put(f"{self.base}/api/speech/state", params={"key": key}, json=data, headers=self.headers, timeout=self.timeout)
        res.raise_for_status()

    def mark(self, kind: str, xcode: str, date_kst: str) -> None:
        res = self.s.put(f"{self.base}/api/speech/mark", params={"kind": kind, "xcode": xcode, "date": date_kst},
                         headers=self.headers, timeout=self.timeout)
        res.raise_for_status()


def state_doc(sent_seqs: set[int], last_seq: int, open_seg: Segment | None, used_seqs: set[int]) -> dict:
    return {
        "version": STATE_VERSION,
        "sent": sorted(sent_seqs),
        "last_seq": last_seq,
        "used": sorted(used_seqs),
        "open": asdict(open_seg) if open_seg else None,
    }


def restore(doc: dict | None) -> tuple[set[int], int, Segment | None, set[int]]:
    if not doc:
        return set(), 0, None, set()
    o = doc.get("open")
    seg = Segment(int(o["seq"]), str(o["member"]), str(o.get("party") or ""), float(o["started_at"]),
                  o.get("ended_at"), list(o.get("lines") or []), str(o.get("flag") or "")) if o else None
    return set(int(s) for s in doc.get("sent") or []), int(doc.get("last_seq") or 0), seg, set(int(s) for s in doc.get("used") or [])
