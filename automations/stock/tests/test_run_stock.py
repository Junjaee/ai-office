"""run_stock.py 의 뼈대가 보고 규칙을 지키는지 확인한다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_stock as mod  # noqa: E402


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('office_repo: "."\noffice_workspace: "home"\nnext_run: "매일 06:30"\ntasks: [quotes, scan, notify]\n',
                 encoding="utf-8")
    return str(p)


@pytest.fixture
def reports(monkeypatch):
    calls = []
    monkeypatch.setattr(mod, "report_status", lambda repo, **kw: calls.append(kw) or True)
    return calls


def test_success_reports_tasks_and_counts(cfg_file, reports):
    def work(cfg, args, progress):
        return {"counts": {"sent": 1, "failed": 0}, "lines": ["기준일 2026-09-19", "[시장] SPY 200일선 위"],
                "tasks": {"quotes": (True, "500종목 시세"), "scan": (True, "SPY 200일선 위"), "notify": (True, "상태 1통")}}

    assert mod.run(["--config", cfg_file], work=work) == 0
    r = reports[0]
    assert r["ok"] is True
    assert [t["id"] for t in r["tasks"]] == ["quotes", "scan", "notify"]
    assert r["log_lines"][1] == "기준일 2026-09-19"
    assert r["workspace"] == "home"


def test_exception_reports_korean_failure(cfg_file, reports):
    def work(cfg, args, progress):
        raise RuntimeError("시세 수집 실패: SPY 조차 받지 못함")

    assert mod.run(["--config", cfg_file], work=work) == 1
    assert reports[0]["ok"] is False
    assert reports[0]["summary"] == "시세를 받아오지 못했어요 (야후가 막았을 수 있어요)"


def test_dry_run_never_reports(cfg_file, reports):
    def work(cfg, args, progress):
        assert args.dry_run
        return {"counts": {"sent": 0}, "lines": [], "tasks": {}}

    assert mod.run(["--config", cfg_file, "--dry-run"], work=work) == 0
    assert reports == []


def test_local_secrets_only_fill_missing_env(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("telegram_bot_token: abc\ntelegram_chat_id: 123\n", encoding="utf-8")
    monkeypatch.delenv(mod.TOKEN_KEY, raising=False)
    monkeypatch.setenv(mod.CHAT_KEY, "keep")
    mod.load_local_secrets({"local_secrets": str(p)})
    import os
    assert os.environ[mod.TOKEN_KEY] == "abc"
    assert os.environ[mod.CHAT_KEY] == "keep"
