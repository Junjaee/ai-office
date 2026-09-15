"""run_hscity.py 뼈대가 보고 규칙(성공/실패/dry-run)을 지키는지 확인."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_hscity as mod  # noqa: E402


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('office_repo: "."\noffice_workspace: "assembly"\nnext_run: "매일 08:00·18:00"\ntasks: [collect, notify]\n',
                 encoding="utf-8")
    return str(p)


@pytest.fixture
def reports(monkeypatch):
    calls = []
    monkeypatch.setattr(mod, "report_status", lambda repo, **kw: calls.append(kw) or True)
    return calls


def test_success_reports_tasks_and_counts(cfg_file, reports):
    def work(cfg, args, progress):
        return {"counts": {"new": 2, "sent": 2, "failed": 0},
                "lines": ["[신규] a", "[신규] b"],
                "tasks": {"collect": (True, "신규 2건"), "notify": (True, "2건 발송")}}

    assert mod.run(["--config", cfg_file], work=work) == 0
    r = reports[0]
    assert r["ok"] is True
    assert r["counts"]["new"] == 2
    assert {t["id"] for t in r["tasks"]} == {"collect", "notify"}
    assert r["workspace"] == "assembly"


def test_exception_reports_korean_failure(cfg_file, reports):
    def work(cfg, args, progress):
        raise RuntimeError("boom")

    assert mod.run(["--config", cfg_file], work=work) == 1
    assert reports[0]["ok"] is False
    assert "RuntimeError: boom" in reports[0]["log_lines"][1]


def test_dry_run_never_reports(cfg_file, reports):
    def work(cfg, args, progress):
        assert args.dry_run
        return {"counts": {"new": 0}, "lines": [], "tasks": {}}

    assert mod.run(["--config", cfg_file, "--dry-run"], work=work) == 0
    assert reports == []
