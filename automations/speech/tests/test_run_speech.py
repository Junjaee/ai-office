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
        question_order=lambda query, days: order,
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
