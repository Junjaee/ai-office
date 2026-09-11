"""run_weekend.py — 뼈대의 보고 규칙과 do_work 흐름 (구글·텔레그램은 가짜, 네트워크 없음)."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_weekend as mod  # noqa: E402


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('office_repo: "."\noffice_workspace: "assembly"\nnext_run: "매주 목 17:00"\ntasks: [fetch, send]\n'
                 'calendar_id: "cal@group.calendar.google.com"\ncalendar_name: "530호 일정"\n', encoding="utf-8")
    return str(p)


@pytest.fixture
def reports(monkeypatch):
    """report_status 를 가짜로 바꿔 호출 인자를 모은다 (git 을 건드리지 않음)."""
    calls = []
    monkeypatch.setattr(mod, "report_status", lambda repo, **kw: calls.append(kw) or True)
    return calls


def test_success_reports_tasks_and_counts(cfg_file, reports):
    def work(cfg, args, progress):
        return {"counts": {"events": 3, "sent": 1}, "lines": ["[전송] 3건"],
                "tasks": {"fetch": (True, "토 2건 · 일 1건"), "send": (True, "보냄")}}

    assert mod.run(["--config", cfg_file], work=work) == 0
    r = reports[0]
    assert r["tasks"] == [{"id": "fetch", "status": "done", "summary": "토 2건 · 일 1건"},
                          {"id": "send", "status": "done", "summary": "보냄"}]
    assert r["summary"].startswith("주말 일정 3건, 전송 1건")
    assert r["workspace"] == "assembly"


def test_exception_reports_korean_failure(cfg_file, reports):
    def work(cfg, args, progress):
        raise RuntimeError("텔레그램 전송 실패: Forbidden")

    assert mod.run(["--config", cfg_file], work=work) == 1
    assert reports[0]["ok"] is False
    assert reports[0]["summary"] == "텔레그램으로 보내지 못했어요"


def test_dry_run_never_reports(cfg_file, reports):
    def work(cfg, args, progress):
        assert args.dry_run
        return {"counts": {"events": 0}, "lines": [], "tasks": {}}

    assert mod.run(["--config", cfg_file, "--dry-run"], work=work) == 0
    assert reports == []


# ───────────────────────── do_work ─────────────────────────

CFG = {"calendar_id": "cal@group.calendar.google.com", "title": "이준석 주말 일정", "tasks": ["fetch", "send"],
       "reveal_keywords": ["동탄"]}
ITEMS = [
    {"summary": "국회 행사", "start": {"dateTime": "2026-09-12T10:00:00+09:00"}, "end": {"dateTime": "2026-09-12T12:00:00+09:00"}},
    {"summary": "지역 방문", "start": {"date": "2026-09-13"}, "end": {"date": "2026-09-14"}},
]


class FakeEvents:
    def __init__(self, items, error=None):
        self.items, self.error, self.calls = items, error, []

    def list(self, **kw):
        self.calls.append(kw)
        return self

    def execute(self):
        if self.error:
            raise self.error
        return {"items": self.items}


class FakeService:
    def __init__(self, items, error=None):
        self._events = FakeEvents(items, error)

    def events(self):
        return self._events


class Args:
    def __init__(self, dry_run=False, find_chat=False):
        self.dry_run, self.find_chat = dry_run, find_chat


@pytest.fixture
def fakes(monkeypatch):
    sent = []
    svc = FakeService(ITEMS)
    monkeypatch.setattr(mod, "today_kst", lambda: date(2026, 9, 10))  # 목요일
    monkeypatch.setattr(mod, "calendar_service", lambda: svc)
    monkeypatch.setattr(mod, "telegram_env", lambda: ("tok", "42"))
    monkeypatch.setattr(mod, "send_message", lambda token, chat, text, **kw: sent.append((chat, text)))
    return svc, sent


def test_do_work_reads_weekend_and_sends(fakes):
    svc, sent = fakes
    result = mod.do_work(CFG, Args(), lambda m: None)
    call = svc.events().calls[0]
    assert call["calendarId"] == "cal@group.calendar.google.com"
    assert (call["timeMin"], call["timeMax"]) == ("2026-09-12T00:00:00+09:00", "2026-09-14T00:00:00+09:00")
    assert call["singleEvents"] is True
    assert sent[0][0] == "42" and "9월 13일 (일)" in sent[0][1]
    assert sent[0][1].startswith("이준석 주말 일정(9/12 토 ~ 9/13 일)")
    assert "행사 일정" in sent[0][1] and "국회 행사" not in sent[0][1]   # 동탄 관련이 아니면 종류만
    assert result["counts"] == {"events": 2, "sent": 1}
    assert all("국회 행사" not in ln and "지역 방문" not in ln for ln in result["lines"])   # 대시보드 기록도 가림
    assert result["tasks"]["fetch"] == (True, "토 1건 · 일 1건")
    assert result["tasks"]["send"][0] is True


def test_do_work_dry_run_prints_and_does_not_send(fakes, capsys):
    _, sent = fakes
    result = mod.do_work(CFG, Args(dry_run=True), lambda m: None)
    assert sent == [] and result["counts"]["sent"] == 0
    assert "행사 일정" in capsys.readouterr().out


def test_do_work_calendar_http_error_becomes_korean(fakes, monkeypatch):
    class Resp:
        status = 403

    class HttpError(Exception):
        resp = Resp()

    monkeypatch.setattr(mod, "calendar_service", lambda: FakeService([], HttpError("insufficient scopes")))
    with pytest.raises(RuntimeError, match="캘린더 읽기 실패: HTTP 403"):
        mod.do_work(CFG, Args(), lambda m: None)


def test_do_work_find_chat_lists_chats_without_sending(fakes, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setattr(mod, "list_chats", lambda token: [{"id": 42, "type": "private", "name": "길동", "username": "hong"}])
    result = mod.do_work(CFG, Args(dry_run=True, find_chat=True), lambda m: None)
    out = capsys.readouterr().out
    assert "42" in out and "길동" in out
    assert fakes[1] == [] and result["counts"] == {}
