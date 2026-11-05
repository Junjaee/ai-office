"""생중계 자막 수신 — 두 종류를 같은 Caption 으로 만들어 큐에 넣는다. 기록(jsonl)·재생도 여기.

- 속기 자막: wss://smi(-hy|-dw)N.webcast.go.kr/<xcode> — socket.io EIO=3(옛 규격, python-socketio<5), 네임스페이스 /<xcode>, 이벤트 "receive message"
- AI 자막: 그 밖 — 일반 WebSocket, 하위 프로토콜 echo-protocol, JSON {segment, transcript, final, scd}. 같은 segment 가 고쳐지며 여러 번 온다 → FinalFilter
둘 다 화자 이름은 없다. 끊기면 10초 뒤 다시 붙는다.

기록 형식(jsonl 한 줄): {"t": "2026-11-05T20:34:42", "kind": "ai"|"stt", "segment": 123, "final": true, "text": "…"}
— 2026-11-05 예결위 녹음(ai-assembly/05_회의발언요약/captions_21_20261105.jsonl)과 같아서 그 파일을 --replay 로 돌릴 수 있다.
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator

from webcast_api import HEADERS, caption_kind

KST = timezone(timedelta(hours=9))
RECONNECT_SEC = 10


@dataclass(frozen=True)
class Caption:
    at: float                 # epoch 초
    text: str
    final: bool = True
    segment: int | None = None   # AI 자막 segment 번호. 속기 자막은 None


class FinalFilter:
    """AI 자막: segment 마다 final 인 것을 한 번만 통과. 속기 자막(segment None)은 늘 통과."""

    def __init__(self) -> None:
        self._seen: set[int] = set()

    def accept(self, c: Caption) -> Caption | None:
        if c.segment is None:
            return c
        if not c.final or c.segment in self._seen:
            return None
        self._seen.add(c.segment)
        return c


def _run_socketio(url: str, xcode: str, out: queue.Queue, stop: threading.Event, log) -> None:
    import socketio  # python-socketio<5

    base = re.sub(r"^wss?://", "https://", url).split("/" + xcode)[0]
    ns = f"/{xcode}"
    sio = socketio.Client(reconnection=False)

    @sio.on("receive message", namespace=ns)
    def on_msg(msg):  # noqa: ANN001
        out.put(Caption(time.time(), str(msg)))

    while not stop.is_set():
        try:
            sio.connect(base, namespaces=[ns], headers={"Origin": HEADERS["Origin"]})
            log("자막 연결(속기)")
            while not stop.is_set() and sio.connected:
                time.sleep(1)
            try:
                sio.disconnect()
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001
            log(f"자막 끊김(속기) {type(exc).__name__}")
            stop.wait(RECONNECT_SEC)


def _run_ws(url: str, out: queue.Queue, stop: threading.Event, log) -> None:
    import websocket  # websocket-client

    while not stop.is_set():
        try:
            ws = websocket.create_connection(url, subprotocols=["echo-protocol"], timeout=60,
                                             header=[f"Origin: {HEADERS['Origin']}"])
            log("자막 연결(AI)")
            while not stop.is_set():
                raw = ws.recv()
                try:
                    d = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                seg = d.get("segment")
                out.put(Caption(time.time(), str(d.get("transcript") or ""), bool(d.get("final")),
                                int(seg) if seg is not None else None))
        except Exception as exc:  # noqa: BLE001
            log(f"자막 끊김(AI) {type(exc).__name__}")
            stop.wait(RECONNECT_SEC)


def start_receiver(xsami: str, xcode: str, out: queue.Queue, stop: threading.Event, log=print) -> threading.Thread:
    """자막 종류에 맞는 수신 스레드(데몬)를 띄운다. log 에는 건수·오류 종류만 넘긴다(공개 로그)."""
    if caption_kind(xsami) == "stt":
        t = threading.Thread(target=_run_socketio, args=(xsami, xcode, out, stop, log), daemon=True)
    else:
        t = threading.Thread(target=_run_ws, args=(xsami, out, stop, log), daemon=True)
    t.start()
    return t


def record_line(fp, c: Caption, kind: str) -> None:
    rec = {"t": datetime.fromtimestamp(c.at, KST).strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind,
           "segment": c.segment, "final": c.final, "text": c.text}
    fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    fp.flush()


def replay(path: str) -> Iterator[Caption]:
    """기록 파일을 Caption 으로 흘려 보낸다(ai·stt 줄만)."""
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("kind") not in ("ai", "stt"):
                continue
            at = datetime.strptime(r["t"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=KST).timestamp()
            seg = r.get("segment")
            yield Caption(at, str(r.get("text") or ""), bool(r.get("final", True)),
                          int(seg) if seg is not None else None)
