"""run_ledger.py — 프레임워크 보고 규칙 + 승인문자 파싱 로직 테스트."""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_ledger as mod  # noqa: E402


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('office_repo: "."\noffice_workspace: "home"\nnext_run: "매시간"\ntasks: [collect, sheet]\n',
                 encoding="utf-8")
    return str(p)


@pytest.fixture
def reports(monkeypatch):
    calls = []
    monkeypatch.setattr(mod, "report_status", lambda repo, **kw: calls.append(kw) or True)
    return calls


# ── 프레임워크 계약 ──
def test_success_reports_tasks_and_counts(cfg_file, reports):
    def work(cfg, args, progress):
        return {"counts": {"new": 2, "replaced": 1, "skip": 0, "failed": 0},
                "lines": ["[추가] a"], "tasks": {"collect": (True, "메일 3건"), "sheet": (True, "추가 2")}}
    assert mod.run(["--config", cfg_file], work=work) == 0
    r = reports[0]
    assert r["ok"] is True
    assert r["workspace"] == "home"
    assert {"id": "collect", "status": "done", "summary": "메일 3건"} in r["tasks"]
    assert {"id": "sheet", "status": "done", "summary": "추가 2"} in r["tasks"]


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


# ── 승인문자 파싱 로직 ──
TODAY = dt.date(2026, 9, 10)


def _sms(*lines):
    return "\n".join(lines)


def test_parse_hyundai_approve():
    t = mod.parse_sms(_sms("[Web발신]", "현대 Amex Gold 승인", "신*재", "24,000원 일시불",
                           "09/10 12:07", "보승회관여의도", "누적4,049,905원"), TODAY)
    assert t["kind"] == "approve" and t["card"] == "현대카드"
    assert t["amount"] == 24000 and t["month"] == 9 and t["day"] == 10
    assert t["detail"] == "보승회관여의도"
    assert mod.classify_item(t["detail"]) == "식비"


def test_parse_kb_approve():
    t = mod.parse_sms(_sms("[Web발신]", "KB국민카드3533승인", "신*재님", "14,000원 일시불",
                           "09/10 14:06", "쿠팡(쿠페이)", "누적287,416원"), TODAY)
    assert t["card"] == "쿠팡와우카드" and t["amount"] == 14000
    assert mod.classify_item(t["detail"]) == "생활비"


def test_cancel_kind_and_ignore():
    t = mod.parse_sms(_sms("[Web발신]", "현대 Amex Gold 취소", "신*재", "1,000원 일시불",
                           "09/10 14:00", "(주)모빌리언스", "누적4,049,905원"), TODAY)
    assert t["kind"] == "cancel" and t["amount"] == 1000
    # 승인거절은 무시(None)
    assert mod.parse_sms(_sms("[Web발신]", "KB국민카드", "신*재님", "09/10 14:01",
                              "(주)케이지모빌리언", "승인거절:문의"), TODAY) is None


def test_card_detect_from_header_not_merchant():
    # KB카드로 '현대백화점' 결제 -> 가맹점에 현대가 있어도 쿠팡와우카드여야 함
    t = mod.parse_sms(_sms("[Web발신]", "KB국민카드3533승인", "신*재님", "50,000원 일시불",
                           "09/10 14:06", "현대백화점무역센터", "누적1원"), TODAY)
    assert t["card"] == "쿠팡와우카드"


def test_year_boundary():
    assert mod.month_key(12, dt.date(2027, 1, 3)) == "2026-12"   # 연초에 처리한 연말 결제
    assert mod.month_key(9, dt.date(2026, 9, 10)) == "2026-09"
