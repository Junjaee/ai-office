"""실행기 — 네트워크 없이 재생(--replay)·가짜 의존성으로 전체 흐름. 공개 로그에 이름·자막이 안 들어가는지도 본다."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_speech  # noqa: E402
from run_speech import Deps, chat_env_key, run  # noqa: E402
from state_store import restore, state_doc  # noqa: E402
from segmenter import Segment  # noqa: E402

CFG = Path(__file__).resolve().parent.parent / "config.actions.yaml"
ROSTER = [(14, "서지영", "국민의힘"), (13, "이준석", "개혁신당")]


def write_replay(path: Path, rows):
    path.write_text("".join(json.dumps({"t": t, "kind": "ai", "segment": i, "final": True, "text": s}, ensure_ascii=False) + "\n"
                            for i, (t, s) in enumerate(rows, 1)), encoding="utf-8")


REPLAY = [
    ("2026-11-05T20:00:00", "서지영 위원님 질의하여 주십시오"),
    ("2026-11-05T20:00:10", "장관님 한 가지 묻겠습니다"),
    ("2026-11-05T20:10:00", "서지영 위원님 수고하셨습니다 다음은 경기 화성을의"),
    ("2026-11-05T20:10:03", "개혁신당 이준석 위원님 질의하여 주십시오"),
    ("2026-11-05T20:10:10", "광역버스 노선이 5개로 줄었습니다"),
    ("2026-11-05T20:30:00", "이준석 위원님 수고하셨습니다"),
    ("2026-11-05T20:30:05", "산회를 선포합니다"),
]


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def json(self, *, system, user, schema):
        self.prompts.append(user)
        return {"topics": [{"title": "주제", "lines": ["무엇을 지적했음", "무엇을 요구했음"]}]}


class FakeState:
    def __init__(self, doc=None):
        self.doc, self.puts, self.marks = doc, [], []

    def get(self, key):
        return self.doc

    def put(self, key, data):
        self.puts.append(data)

    def mark(self, kind, xcode, date_kst):
        self.marks.append((kind, xcode, date_kst))


def fake_deps(state=None, order=ROSTER):
    sent, reports = [], []
    llm = FakeLLM()
    d = Deps(
        question_order=lambda query, days, date="": order,
        make_llm=lambda: llm,
        sender=lambda token, chat, text: sent.append((chat, text)),
        state=state or FakeState(),
        report=lambda **kw: reports.append(kw),
        fetch=lambda path, params=None: (_ for _ in ()).throw(AssertionError("네트워크 호출 금지")),
        today=lambda: "2026-11-05",
    )
    d.sent, d.reports, d.llm = sent, reports, llm
    return d


def test_replay_dry_run_writes_messages(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTICE_530_BOT_TOKEN", "t")
    rec, out = tmp_path / "rec.jsonl", tmp_path / "out.txt"
    write_replay(rec, REPLAY)
    deps = fake_deps()
    assert run(["--config", str(CFG), "--xcode", "21", "--replay", str(rec), "--out", str(out)], deps) == 0
    text = out.read_text(encoding="utf-8")
    assert "🔵 개혁신당 이준석 · 질의 13" in text
    assert "📋" in text and "질의 14" in text          # 서지영은 산회 때 묶음으로
    assert "◯ 무엇을 지적했음" in text
    assert deps.sent == []                             # 재생은 보내지 않는다
    assert "[위원: 이준석]" in deps.llm.prompts[-1] and "광역버스 노선이 5개로 줄었습니다" in deps.llm.prompts[-1]


def test_report_counts_only(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTICE_530_BOT_TOKEN", "t")
    rec, out = tmp_path / "rec.jsonl", tmp_path / "out.txt"
    write_replay(rec, REPLAY)
    deps = fake_deps()
    run(["--config", str(CFG), "--xcode", "21", "--replay", str(rec), "--out", str(out)], deps)
    rep = deps.reports[-1]
    blob = rep["summary"] + " ".join(rep.get("log_lines") or []) + " ".join(t["summary"] for t in rep["tasks"])
    for secret in ("이준석", "서지영", "광역버스", "장관님"):
        assert secret not in blob
    assert rep["counts"]["segments"] == 2 and rep["counts"]["summarized"] == 2 and rep["ok"] is True
    assert {t["id"] for t in rep["tasks"]} == {"listen", "summarize", "notify"}


def test_restore_open_segment(tmp_path, monkeypatch):
    monkeypatch.setenv("NOTICE_530_BOT_TOKEN", "t")
    rec, out = tmp_path / "rec.jsonl", tmp_path / "out.txt"
    write_replay(rec, [("2026-11-05T20:05:00", "이어지는 줄"), ("2026-11-05T20:06:00", "서지영 위원님 수고하셨습니다"),
                       ("2026-11-05T20:06:05", "산회를 선포합니다")])
    # 열린 구간은 재생 첫 줄(20:05)보다 조금 앞에 시작한 것 — 25분 규칙에 걸리지 않게
    started = datetime(2026, 11, 5, 20, 4, tzinfo=timezone(timedelta(hours=9))).timestamp()
    open_seg = Segment(14, "서지영", "국민의힘", started, None, ["이전 줄"])
    deps = fake_deps(state=FakeState(state_doc({1, 2}, 2, open_seg, {1, 2, 14})))
    run(["--config", str(CFG), "--xcode", "21", "--replay", str(rec), "--out", str(out), "--key", "DCM1"], deps)
    assert "이전 줄\n이어지는 줄" in deps.llm.prompts[0]


def test_state_doc_roundtrip():
    seg = Segment(14, "서지영", "국민의힘", 10.0, None, ["가", "나"], "no_call")
    sent, last, cur, used = restore(state_doc({1, 2}, 2, seg, {1, 2, 14}))
    assert sent == {1, 2} and last == 2 and used == {1, 2, 14}
    assert cur == seg
    assert restore(None) == (set(), 0, None, set())


def test_notify_target_picks_chat_env():
    assert chat_env_key({"notify_target": "preview"}) == "TELEGRAM_CHAT_ID"
    assert chat_env_key({"notify_target": "group"}) == "NOTICE_530_CHAT_ID"
    assert chat_env_key({}) == "TELEGRAM_CHAT_ID"


def test_skip_day_marks_and_reports(monkeypatch):
    monkeypatch.setenv("NOTICE_530_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    deps = fake_deps(order=[(1, "김남준", "더불어민주당"), (2, "이춘석", "더불어민주당")])
    assert run(["--config", str(CFG), "--xcode", "65", "--request-id", "req-1"], deps) == 0
    assert deps.state.marks == [("skip", "65", "2026-11-05")]
    assert deps.sent == []
    rep = deps.reports[-1]
    assert "오늘 질의 없음" in rep["summary"] and rep["ok"] is True
    assert all(t["status"] == "done" for t in rep["tasks"])


def test_window_end_default_is_three_hours():
    """손으로 켠 실행(window_end 없음)은 3시간만 기다린다 — live_list 의 xstat 은 회의가 끝나도 1 로 남아(2026-11-06 실측)
    '방송 중' 판정만으로는 끝을 모르므로 시간대로 끊는다. Worker 가 깨운 실행은 캘린더 시간대를 받는다."""
    from run_speech import parse_window_end

    assert parse_window_end("", 1000.0) == 1000.0 + 3 * 3600
    assert parse_window_end("2026-11-05T23:00:00+09:00", 0) == datetime(2026, 11, 5, 23, 0, tzinfo=timezone(timedelta(hours=9))).timestamp()


# ───────── 생중계 흐름(가짜 수신기·가짜 시계) — 검토 2·3·4·5·7 ─────────

LIVE_LIST = ('[{"xcode":"21","xcgcd":"DCM000021224390401","xname":"예결위","xstat":"1","xdesc":"속개",'
             '"xsubj":"제439회 제04차 예산결산특별위원회 [00:00]"}]')
PLAY = '{"xsami":"wss://smiai.webcast.go.kr:8091/aistt/special"}'
MAP = '[{"mname":"서지영","mdang":"국민의힘"}]'


class Clock:
    def __init__(self, t=1_762_300_000.0):
        self.t = t

    def now(self):
        self.t += 5
        return self.t

    def sleep(self, s):
        self.t += s


def live_deps(captions, *, fail_live_list_after=None, state=None):
    """captions: 수신 스레드가 큐에 넣을 (지연초, 글) 목록. 다 넣고 나면 조용하다."""
    import threading

    from captions import Caption

    clock = Clock()
    calls = {"live_list": 0, "receiver": 0}

    def fetch(path, params=None):
        if path == "live_list.asp":
            calls["live_list"] += 1
            if fail_live_list_after is not None and calls["live_list"] > fail_live_list_after:
                raise ConnectionError("끊김")
            return LIVE_LIST
        if path == "live_play.asp":
            return PLAY
        if path == "live_map.asp":
            return MAP
        raise AssertionError(path)

    def start_receiver(xsami, xcode, out, stop, log=print):
        calls["receiver"] += 1
        if calls["receiver"] == 1:
            for dt, text in captions:
                out.put(Caption(clock.t + dt, text))
        return threading.Thread(target=lambda: None)

    st = state or FakeState()
    st.gets = []
    orig_get = st.get
    st.get = lambda key: (st.gets.append(key), orig_get(key))[1]
    deps = fake_deps(state=st, order=ROSTER)
    deps.fetch, deps.now, deps.sleep = fetch, clock.now, clock.sleep
    days = iter(["2026-11-05", "2026-11-06", "2026-11-06", "2026-11-06"])
    deps.today = lambda: next(days)
    deps.start_receiver = start_receiver
    deps.calls, deps.clock = calls, clock
    return deps


def run_live(deps, monkeypatch, tmp_path, window_sec=120):
    monkeypatch.setenv("NOTICE_530_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setattr(run_speech, "start_receiver", deps.start_receiver)
    monkeypatch.setattr(run_speech, "SILENCE_SEC", 60)
    out = tmp_path / "out.txt"
    end = datetime.fromtimestamp(deps.clock.t + window_sec, timezone.utc).isoformat()
    code = run(["--config", str(CFG), "--xcode", "21", "--window-end", end, "--dry-run", "--out", str(out)], deps)
    return code, (out.read_text(encoding="utf-8") if out.exists() else "")


def test_window_end_sends_remainder_without_done_marker(monkeypatch, tmp_path):
    deps = live_deps([(1, "서지영 위원님 질의하여 주십시오"), (2, "질의 한 줄"), (3, "서지영 위원님 수고하셨습니다")])
    code, out = run_live(deps, monkeypatch, tmp_path)
    assert code == 0
    assert "질의 14" in out                      # 산회 없이 시간대가 끝나도 남은 것은 보낸다
    assert deps.state.marks == []                # window_end 로 끝나면 '끝남' 표시를 쓰지 않는다(다른 일정이 막히지 않게)
    assert deps.state.gets[0] == "2026-11-05-21-DCM000021224390401"   # 상태 키에 시작 날짜·채널


def test_adjourn_marks_done_with_start_date(monkeypatch, tmp_path):
    deps = live_deps([(1, "서지영 위원님 질의하여 주십시오"), (2, "질의"), (3, "산회를 선포합니다")])
    code, _ = run_live(deps, monkeypatch, tmp_path)
    assert code == 0
    assert deps.state.marks == [("done", "21", "2026-11-05")]   # 자정을 넘겨 끝나도 시작한 날짜


def test_silence_reconnects_and_live_list_error_does_not_kill(monkeypatch, tmp_path):
    # live_list: 1회(시작 확인) · 2회(자막 끊긴 뒤 다시 붙기) 는 되고, 그 뒤는 끊긴다 → 오류로 죽지 않고 시간대 끝까지 간다
    deps = live_deps([(1, "서지영 위원님 질의하여 주십시오"), (2, "질의")], fail_live_list_after=2)
    code, out = run_live(deps, monkeypatch, tmp_path, window_sec=400)
    assert code == 0
    assert deps.calls["receiver"] >= 2            # 자막이 끊기면 방송 상태와 상관없이 다시 붙는다
    rep = deps.reports[-1]
    assert rep["ok"] is True and "질의 14" in out  # 열린 구간은 끝에서 닫혀 보내진다


def test_zero_captions_marks_listen_error(monkeypatch, tmp_path):
    deps = live_deps([])
    code, _ = run_live(deps, monkeypatch, tmp_path, window_sec=60)
    assert code == 0
    rep = deps.reports[-1]
    assert [t for t in rep["tasks"] if t["id"] == "listen"][0]["status"] == "error"


def test_deadline_caps_window():
    from run_speech import MAX_RUN_SEC, effective_window_end

    assert effective_window_end(1000.0 + 10 * 3600, 1000.0) == 1000.0 + MAX_RUN_SEC
    assert effective_window_end(1000.0 + 60, 1000.0) == 1000.0 + 60
    assert MAX_RUN_SEC <= 345 * 60


def test_skip_mark_failure_does_not_fail_run(monkeypatch):
    monkeypatch.setenv("NOTICE_530_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    st = FakeState()
    st.mark = lambda *a: (_ for _ in ()).throw(RuntimeError("Worker 응답 없음"))
    deps = fake_deps(state=st, order=[(1, "김남준", "더불어민주당")])
    assert run(["--config", str(CFG), "--xcode", "65"], deps) == 0
    assert "오늘 질의 없음" in deps.reports[-1]["summary"]
