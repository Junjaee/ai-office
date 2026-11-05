"""회의 발언 요약 자동화 — 생중계 자막을 받아 위원별로 요약하고 530 알림으로 보낸다 (설계 3절).

사용:
  python run_speech.py --xcode 21 [--window-end 2026-11-05T23:00:00+09:00] [--request-id req-…]
  python run_speech.py --replay 녹음.jsonl --xcode 21 --out 결과.txt     # 네트워크·전송 없이 재생 (이 PC 시험용)
  python run_speech.py --xcode 21 --dry-run --out 결과.txt               # 받되 보내지 않고 파일에 쓴다
  python run_speech.py --xcode 21 --record 녹음.jsonl                    # 받은 자막을 같이 기록

로그(공개 저장소)에는 건수와 오류 종류만 찍는다. 자막·요약·위원 이름은 텔레그램과 R2 에만.
"""
from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "common"))

from errors import to_korean  # noqa: E402
from captions import Caption, FinalFilter, record_line, replay, start_receiver  # noqa: E402
from dispatcher import Batch, Dispatcher, render_messages  # noqa: E402
from segmenter import Segment, Segmenter  # noqa: E402
from state_store import StateClient, restore, state_doc  # noqa: E402
from summarizer import MemberSummary, failed_summary, load_attendees, render_member, summarize  # noqa: E402
import webcast_api as api  # noqa: E402

try:
    from report_status import report as report_status  # noqa: E402
except ImportError:
    report_status = None

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "speech"
AUTOMATION_NAME = "회의 발언 요약"
DEPT = "qa"
POLL_SEC = 60            # 방송 대기 중 live_list 확인 간격
SAVE_SEC = 30            # 상태 저장 간격
SILENCE_SEC = 600        # 자막이 이만큼 없으면 방송 상태를 다시 본다


# ───────────────────────── 바깥 세상과 닿는 것(시험에서 바꿔 끼운다) ─────────────────────────

def _default_question_order(query: str, days: int):
    from order_hwp import fetch_question_order

    return fetch_question_order(query, days)


def _default_make_llm():
    from llm import LLM

    return LLM(["claude_cli", "gemini"])


def _default_sender(token: str, chat: str, text: str) -> None:
    from telegram_bot import send_message

    send_message(token, chat, text)


@dataclass
class Deps:
    question_order: Callable = _default_question_order
    make_llm: Callable = _default_make_llm
    sender: Callable[[str, str, str], None] = _default_sender
    state: object | None = None                       # StateClient 모양(get/put/mark). None 이면 설정의 주소로 만든다
    report: Callable | None = None                    # report_status.report 모양
    fetch: Callable = api.fetch                       # (path, params) -> str
    now: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    today: Callable[[], str] = lambda: datetime.now(KST).strftime("%Y-%m-%d")


# ───────────────────────── 순수 도우미 ─────────────────────────

def chat_env_key(cfg: dict) -> str:
    """notify_target: preview → 사용자 개인 대화방, group → 530 단체방 (설계 9절)."""
    return "NOTICE_530_CHAT_ID" if (cfg.get("notify_target") or "preview") == "group" else "TELEGRAM_CHAT_ID"


def roster_from_order(rows: list[tuple[int, str, str]], special: str) -> dict[str, tuple[int, str]]:
    roster = {name: (seq, party) for seq, name, party in rows}
    roster.setdefault(special, (0, ""))
    return roster


def roster_from_members(members: list[tuple[str, str]], special: str) -> dict[str, tuple[int, str]]:
    roster = {name: (0, party) for name, party in members}
    roster.setdefault(special, (0, ""))
    return roster


def special_in(rows: list[tuple[int, str, str]], special: str) -> bool:
    return any(name == special for _, name, _ in rows)


def parse_window_end(raw: str, now: float) -> float:
    if raw and raw.strip():
        return datetime.fromisoformat(raw.strip()).timestamp()
    return now + 8 * 3600


# ───────────────────────── 한 회의 ─────────────────────────

class Session:
    """자막 → 구간 → (백그라운드) 요약 → 묶음 → 전송. 순수 규칙은 전부 다른 모듈, 여기는 이어 붙이기만."""

    def __init__(self, cfg: dict, deps: Deps, meeting: str, roster: dict[str, tuple[int, str]],
                 attendees: list[str], *, out_path: str | None, sync: bool) -> None:
        self.cfg, self.deps, self.meeting = cfg, deps, meeting
        self.special = str(cfg.get("special_member") or "이준석")
        self.attendees = attendees
        self.out_path, self.sync = out_path, sync
        self.segmenter = Segmenter(roster, self.special, int(cfg.get("segment_max_minutes") or 25))
        self.dispatcher = Dispatcher(int(cfg.get("batch_size") or 10), self.special)
        self.topics_max = int(cfg.get("summary_topics_max") or 8)
        self.llm = None
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.futures: list[tuple[Future, Segment]] = []
        self.sent_seqs: set[int] = set()
        self.last_seq = 0
        self.adjourned = False
        self.counts = {"captions": 0, "segments": 0, "summarized": 0, "summary_failed": 0, "sent": 0, "send_failed": 0}
        self.errors: list[str] = []
        self.token = os.environ.get("NOTICE_530_BOT_TOKEN", "")
        self.chat = os.environ.get(chat_env_key(cfg), "")

    # 상태
    def restore(self, doc: dict | None) -> None:
        sent, last, cur, used = restore(doc)
        self.sent_seqs, self.last_seq = sent, last
        self.segmenter.restore(cur, used)
        self.dispatcher = Dispatcher(self.dispatcher.batch_size, self.special, sent)

    def snapshot(self) -> dict:
        return state_doc(self.sent_seqs, self.last_seq, self.segmenter.current, self.segmenter._used)

    # 흐름
    def process(self, c: Caption) -> None:
        self.counts["captions"] += 1
        for ev in self.segmenter.feed(c):
            if ev[0] == "close":
                self._closed(ev[1])
            elif ev[0] == "special_call":
                self._send_all(self.dispatcher.special_called())
            elif ev[0] == "adjourn":
                self.adjourned = True
        self.pump()

    def _closed(self, seg: Segment) -> None:
        self.counts["segments"] += 1
        self.last_seq = max(self.last_seq, seg.seq)
        if not seg.lines:
            return
        if self.sync:
            self._ready(self._summarize(seg))
        else:
            self.futures.append((self.pool.submit(self._summarize, seg), seg))

    def _summarize(self, seg: Segment) -> MemberSummary:
        try:
            if self.llm is None:
                self.llm = self.deps.make_llm()
            ms = summarize(seg, self.meeting, self.attendees, self.llm, self.topics_max)
            self.counts["summarized"] += 1
            return ms
        except Exception as exc:  # noqa: BLE001 - 요약 실패는 자리표시로 대신하고 계속
            self.counts["summary_failed"] += 1
            self.errors.append(f"요약 실패 {type(exc).__name__}")
            return failed_summary(seg)

    def pump(self) -> None:
        done = [(f, s) for f, s in self.futures if f.done()]
        self.futures = [(f, s) for f, s in self.futures if not f.done()]
        for f, _ in sorted(done, key=lambda fs: fs[1].seq):
            self._ready(f.result())

    def _ready(self, ms: MemberSummary) -> None:
        self._send_all(self.dispatcher.ready(ms))

    def _send_all(self, batches: list[Batch]) -> None:
        for b in batches:
            for text in render_messages(b, self.meeting):
                if self.out_path:
                    with open(self.out_path, "a", encoding="utf-8") as fp:
                        fp.write(text + "\n\n" + "─" * 20 + "\n\n")
                else:
                    try:
                        self.deps.sender(self.token, self.chat, text)
                    except Exception as exc:  # noqa: BLE001
                        self.counts["send_failed"] += 1
                        self.errors.append(f"전송 실패 {type(exc).__name__}")
                        continue
            self.counts["sent"] += 1
            self.sent_seqs.update(b.seqs())

    def finish(self) -> None:
        """끝: 남은 요약을 기다려 거두고, 큐에 남은 것을 전부 보낸다."""
        for f, _ in self.futures:
            f.result()
        self.pump()
        if self.segmenter.current and self.segmenter.current.lines:
            self._closed(self.segmenter._close(self.deps.now()))
            for f, _ in self.futures:
                f.result()
            self.pump()
        self._send_all(self.dispatcher.flush())
        self.pool.shutdown(wait=True)


# ───────────────────────── 실행 ─────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"))
    p.add_argument("--xcode", default="", help="생중계 채널 번호. 비우면 지금 방송 중인 채널")
    p.add_argument("--window-end", default="", help="이 시각(ISO)까지 방송을 기다린다")
    p.add_argument("--request-id", default="")
    p.add_argument("--replay", default="", help="자막 기록(jsonl)을 재생 — 네트워크·전송 없음")
    p.add_argument("--dry-run", action="store_true", help="보내지 않고 --out 파일에 쓴다")
    p.add_argument("--out", default="", help="dry-run 메시지를 쓸 파일")
    p.add_argument("--record", default="", help="받은 자막을 이 파일에 기록")
    p.add_argument("--key", default="", help="상태 저장 키(비우면 회의 xcgcd)")
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


def _log(msg: str) -> None:
    print(f"  · {msg}", flush=True)


def _report(cfg: dict, deps: Deps, *, ok: bool, summary: str, counts: dict, tasks: dict, started_at: str,
            started: float, lines: list[str] | None = None) -> None:
    fn = deps.report or (lambda **kw: report_status(cfg.get("office_repo") or ".", **kw) if report_status else None)
    task_list = [{"id": tid, "status": "done" if tasks.get(tid, (True, ""))[0] else "error", "summary": tasks.get(tid, (True, ""))[1]}
                 for tid in cfg.get("tasks") or []]
    fn(automation_id=AUTOMATION_ID, name=AUTOMATION_NAME, dept=DEPT, ok=ok, summary=summary, counts=counts,
       next_run=cfg.get("next_run", ""), log_lines=lines or [], link=cfg.get("result_link", ""),
       workspace=cfg.get("office_workspace", "assembly"), tasks=task_list, started_at=started_at,
       duration_sec=int(time.monotonic() - started))


def _pick_live_xcode(cfg: dict, deps: Deps) -> str:
    text = deps.fetch("live_list.asp", None)
    for xcode in cfg.get("channels") or {}:
        if api.is_live(api.channel_info(str(xcode), text)):
            return str(xcode)
    return ""


def _wait_for_live(xcode: str, window_end: float, deps: Deps) -> dict | None:
    while True:
        try:
            info = api.channel_info(xcode, deps.fetch("live_list.asp", None))
            if api.is_live(info):
                return info
        except Exception as exc:  # noqa: BLE001
            _log(f"방송 확인 실패 {type(exc).__name__}")
        if deps.now() >= window_end:
            return None
        deps.sleep(POLL_SEC)


def _live_loop(session: Session, xcode: str, window_end: float, deps: Deps, record_fp) -> None:
    """방송이 끝날(산회·시간대 종료) 때까지: 대기 → 수신 → 끊기면 다시 대기."""
    while not session.adjourned and deps.now() < window_end:
        info = _wait_for_live(xcode, window_end, deps)
        if not info:
            return
        xsami = api.parse_xsami(deps.fetch("live_play.asp", {"xcode": xcode, "xcgcd": info["xcgcd"]}))
        if not xsami.startswith("ws"):
            _log("자막 주소 없음 — 1분 뒤 다시")
            deps.sleep(POLL_SEC)
            continue
        kind = api.caption_kind(xsami)
        q: queue.Queue = queue.Queue()
        stop = threading.Event()
        start_receiver(xsami, xcode, q, stop, log=_log)
        flt = FinalFilter()
        last_caption = deps.now()
        last_save = deps.now()
        try:
            while not session.adjourned and deps.now() < window_end:
                try:
                    c = q.get(timeout=1)
                except queue.Empty:
                    c = None
                if c is not None:
                    last_caption = deps.now()
                    if record_fp:
                        record_line(record_fp, c, kind)
                    c2 = flt.accept(c)
                    if c2:
                        session.process(c2)
                else:
                    session.pump()
                if deps.now() - last_save >= SAVE_SEC:
                    last_save = deps.now()
                    _save(session)
                if deps.now() - last_caption >= SILENCE_SEC:
                    if not api.is_live(api.channel_info(xcode, deps.fetch("live_list.asp", None))):
                        _log("방송 끊김 — 다시 기다림")
                        break
                    last_caption = deps.now()
        finally:
            stop.set()


def _save(session: Session) -> None:
    try:
        session.deps.state.put(session.key, session.snapshot())  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        _log(f"상태 저장 실패 {type(exc).__name__}")


def run(argv: list[str], deps: Deps | None = None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config)
    deps = deps or Deps()
    if deps.state is None:
        deps.state = StateClient(str(cfg.get("state_api_base") or ""), os.environ.get("LIVE_TOKEN", ""))
    started_at = datetime.now(KST).isoformat(timespec="seconds")
    started = time.monotonic()
    special = str(cfg.get("special_member") or "이준석")
    attendees = load_attendees(str(HERE / "attendees.yaml")) if (HERE / "attendees.yaml").exists() else []
    replaying = bool(args.replay)
    out_path = args.out if (args.dry_run or replaying) else None
    if (args.dry_run or replaying) and not out_path:
        out_path = os.devnull
    tasks: dict[str, tuple[bool, str]] = {}
    counts: dict = {}
    try:
        xcode = str(args.xcode or "").strip()
        if not xcode and not replaying:
            xcode = _pick_live_xcode(cfg, deps)
            if not xcode:
                _report(cfg, deps, ok=True, summary="방송 중인 회의 없음", counts={}, started_at=started_at, started=started,
                        tasks={"listen": (True, "방송 없음"), "summarize": (True, ""), "notify": (True, "")})
                return 0
        channel_name = str((cfg.get("channels") or {}).get(xcode) or xcode)

        # 0. 질의순서 → 명단, 그리고 "우리 의원 날"인지
        rows = None
        query = (cfg.get("order_mail") or {}).get(xcode)
        if query:
            try:
                rows = deps.question_order(query, int(cfg.get("order_lookback_days") or 3))
            except Exception as exc:  # noqa: BLE001
                _log(f"질의순서 못 읽음 {type(exc).__name__}")
        if rows is not None and cfg.get("special_member_only_days") and not special_in(rows, special) and not replaying:
            deps.state.mark("skip", xcode, deps.today())  # type: ignore[union-attr]
            _report(cfg, deps, ok=True, summary=f"오늘 질의 없음 — {channel_name} 질의순서 {len(rows)}명에 없음", counts={"order": len(rows)},
                    started_at=started_at, started=started,
                    tasks={"listen": (True, "오늘 질의 없음"), "summarize": (True, "건너뜀"), "notify": (True, "건너뜀")})
            return 0
        roster = roster_from_order(rows, special) if rows else {}
        lines: list[str] = [f"질의순서 {len(rows)}명" if rows else "질의순서 없이 진행"]

        if replaying:
            meeting = f"{channel_name} (재생)"
            session = Session(cfg, deps, meeting, roster, attendees, out_path=out_path, sync=True)
            session.key = args.key or "replay"
            session.restore(deps.state.get(session.key) if args.key else None)  # type: ignore[union-attr]
            flt = FinalFilter()
            for c in replay(args.replay):
                c2 = flt.accept(c)
                if c2:
                    session.process(c2)
            session.finish()
        else:
            window_end = parse_window_end(args.window_end, deps.now())
            info = _wait_for_live(xcode, window_end, deps)
            if not info:
                _report(cfg, deps, ok=True, summary=f"{channel_name} 방송이 시작되지 않음", counts={}, started_at=started_at, started=started,
                        tasks={"listen": (True, "방송 없음"), "summarize": (True, ""), "notify": (True, "")})
                return 0
            meeting = api.meeting_title(info) or channel_name
            if not roster:
                try:
                    roster = roster_from_members(api.parse_members(deps.fetch("live_map.asp", {"xcode": xcode})), special)
                except Exception as exc:  # noqa: BLE001
                    _log(f"의석 명단 못 읽음 {type(exc).__name__}")
            session = Session(cfg, deps, meeting, roster, attendees, out_path=out_path, sync=False)
            session.key = args.key or str(info.get("xcgcd") or xcode)
            try:
                session.restore(deps.state.get(session.key))  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                _log(f"상태 복원 실패 {type(exc).__name__}")
            record_fp = open(args.record, "a", encoding="utf-8") if args.record else None
            try:
                _live_loop(session, xcode, window_end, deps, record_fp)
            finally:
                if record_fp:
                    record_fp.close()
            session.finish()
            _save(session)
            try:
                deps.state.mark("done", xcode, deps.today())  # type: ignore[union-attr]
            except Exception as exc:  # noqa: BLE001
                _log(f"끝남 표시 실패 {type(exc).__name__}")

        counts = dict(session.counts)
        c = counts
        summary = f"{channel_name} 자막 {c['captions']}줄 · 구간 {c['segments']} · 요약 {c['summarized']}/{c['summary_failed']}실패 · 전송 {c['sent']}묶음"
        if session.adjourned:
            summary += " · 산회"
        tasks = {
            "listen": (True, f"자막 {c['captions']}줄, 구간 {c['segments']}"),
            "summarize": (c["summary_failed"] == 0, f"요약 {c['summarized']}건" + (f", 실패 {c['summary_failed']}" if c["summary_failed"] else "")),
            "notify": (c["send_failed"] == 0, f"전송 {c['sent']}묶음" + (f", 실패 {c['send_failed']}" if c["send_failed"] else "")),
        }
        lines += sorted(set(session.errors))[:3]
        _log(summary)
        if not replaying or deps.report:
            _report(cfg, deps, ok=all(ok for ok, _ in tasks.values()), summary=summary, counts=counts, started_at=started_at,
                    started=started, tasks=tasks, lines=lines)
        return 0
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _report(cfg, deps, ok=False, summary=to_korean(exc), counts=counts, started_at=started_at, started=started,
                tasks={"listen": (False, type(exc).__name__), "summarize": (True, ""), "notify": (True, "")})
        return 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
