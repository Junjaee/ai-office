"""run___ID__.py 의 뼈대가 보고 규칙을 지키는지 확인한다. do_work 의 실제 로직 테스트는 아래에 추가한다."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run___ID__ as mod  # noqa: E402


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('office_repo: "."\noffice_workspace: "__WORKSPACE__"\nnext_run: "매일 09:00"\ntasks: [collect]\n', encoding="utf-8")
    return str(p)


@pytest.fixture
def reports(monkeypatch):
    """report_status 를 가짜로 바꿔 호출 인자를 모은다 (git 을 건드리지 않음)."""
    calls = []
    monkeypatch.setattr(mod, "report_status", lambda repo, **kw: calls.append(kw) or True)
    return calls


def test_success_reports_tasks_and_counts(cfg_file, reports):
    def work(cfg, args, progress):
        return {"counts": {"new": 2, "failed": 0, "total": 10}, "lines": ["[신규] a", "[신규] b"],
                "tasks": {"collect": (True, "신규 2건")}}

    assert mod.run(["--config", cfg_file], work=work) == 0
    assert len(reports) == 1
    r = reports[0]
    assert r["ok"] is True
    assert r["counts"]["total"] == 10
    assert r["tasks"] == [{"id": "collect", "status": "done", "summary": "신규 2건"}]
    assert r["summary"].startswith("신규 2건, 실패 0건")
    assert r["workspace"] == "__WORKSPACE__"


def test_exception_reports_korean_failure(cfg_file, reports):
    def work(cfg, args, progress):
        raise RuntimeError("boom")

    assert mod.run(["--config", cfg_file], work=work) == 1
    assert reports[0]["ok"] is False
    assert reports[0]["summary"] == "실행 중 문제가 생겼어요"
    assert "RuntimeError: boom" in reports[0]["log_lines"][1]


def test_dry_run_never_reports(cfg_file, reports):
    def work(cfg, args, progress):
        assert args.dry_run
        return {"counts": {"new": 0}, "lines": [], "tasks": {}}

    assert mod.run(["--config", cfg_file, "--dry-run"], work=work) == 0
    assert reports == []
