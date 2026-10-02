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


# ── 라벨 규칙 ──
import types


class _Call:
    def __init__(self, sink, mid, body, removed=None):
        self.sink, self.mid, self.body, self.removed = sink, mid, body, removed

    def execute(self):
        self.sink.append((self.mid, tuple(self.body["addLabelIds"])))
        if self.removed is not None and self.body.get("removeLabelIds"):
            self.removed.append((self.mid, tuple(self.body["removeLabelIds"])))
        return {}


class _Messages:
    def __init__(self, sink, removed=None):
        self.sink, self.removed = sink, removed

    def modify(self, userId, id, body):
        return _Call(self.sink, id, body, self.removed)


class FakeGmail:
    def __init__(self):
        self.labeled = []
        self.unlabeled = []
        self._m = _Messages(self.labeled, self.unlabeled)

    def users(self):
        return self

    def messages(self):
        return self._m


TABS = {"2026년 9월": 1, "2026년 8월": 2}      # 시트에 실제로 있는 월 탭


def _wire(monkeypatch, gmail, bodies, dry_run=False, tabs=TABS):
    monkeypatch.setattr(mod, "get_services", lambda p: (gmail, object()))
    monkeypatch.setattr(mod, "ensure_label",
                        lambda g, name=mod.PROCESSED_LABEL: "L1" if name == mod.PROCESSED_LABEL else "P1")
    monkeypatch.setattr(mod, "fetch_messages", lambda g: [{"id": k} for k in bodies])
    monkeypatch.setattr(mod, "get_body_text", lambda g, mid: bodies[mid])
    monkeypatch.setattr(mod, "sheet_tabs", lambda s: dict(tabs))
    monkeypatch.setattr(mod, "insert_transaction", lambda *a: 6)
    monkeypatch.setattr(mod, "dt", types.SimpleNamespace(
        date=types.SimpleNamespace(today=lambda: dt.date(2026, 9, 22))))
    return types.SimpleNamespace(dry_run=dry_run, token=None)


APPROVE = _sms("[Web발신]", "현대 Amex Gold 승인", "신*재", "24,000원 일시불",
               "09/10 12:07", "보승회관여의도", "누적4,049,905원")


def test_unparsable_mail_is_labeled_so_it_is_not_seen_again(monkeypatch):
    g = FakeGmail()
    args = _wire(monkeypatch, g, {"bad": "{sms_message}", "good": APPROVE})
    result = mod.do_work({}, args, lambda m: None)
    assert result["counts"] == {"new": 1, "replaced": 0, "skip": 1, "wait": 0, "failed": 0}
    assert sorted(g.labeled) == [("bad", ("L1",)), ("good", ("L1",))]


def test_dry_run_labels_nothing(monkeypatch):
    g = FakeGmail()
    args = _wire(monkeypatch, g, {"bad": "{sms_message}", "good": APPROVE}, dry_run=True)
    mod.do_work({}, args, lambda m: None)
    assert g.labeled == []


DEC = _sms("[Web발신]", "현대 Amex Gold 승인", "신*재", "1,000원 일시불",
           "12/01 10:00", "어딘가", "누적1원")


def test_missing_month_tab_gets_pending_label_not_done(monkeypatch):
    # 그 달 탭이 없으면 완료가 아니라 '대기' 라벨 — Worker 의 1분 감시가 같은 문자로 계속 깨우지 않게(2026-10 사고)
    g = FakeGmail()
    args = _wire(monkeypatch, g, {"dec": DEC})
    result = mod.do_work({}, args, lambda m: None)
    assert result["lines"] == ["[대기] 시트에 '2026년 12월' 탭이 없어 1건 보류 — 탭을 만들면 다음 실행 때 들어가요"]
    assert result["counts"] == {"new": 0, "replaced": 0, "skip": 0, "wait": 1, "failed": 0}
    assert "대기 1" in result["tasks"]["sheet"][1]
    assert g.labeled == [("dec", ("P1",))]
    assert "대기 1건" in mod.build_summary(result["counts"], 1)


def test_pending_is_done_once_the_tab_exists(monkeypatch):
    # 탭이 생기면 보류분이 들어가고, 완료 라벨을 붙이면서 대기 라벨은 뗀다
    g = FakeGmail()
    args = _wire(monkeypatch, g, {"dec": DEC}, tabs={**TABS, "2026년 12월": 7})
    result = mod.do_work({}, args, lambda m: None)
    assert result["counts"]["new"] == 1 and result["counts"]["wait"] == 0
    assert g.labeled == [("dec", ("L1",))]
    assert g.unlabeled == [("dec", ("P1",))]


def test_dry_run_does_not_label_pending(monkeypatch):
    g = FakeGmail()
    args = _wire(monkeypatch, g, {"dec": DEC}, dry_run=True)
    result = mod.do_work({}, args, lambda m: None)
    assert result["counts"]["wait"] == 1 and g.labeled == []


def test_month_tab_name_and_query():
    assert mod.month_tab("2026-10") == "2026년 10월" and mod.month_tab("2026-07") == "2026년 7월"
    q = mod.fetch_query()
    assert "-label:카드동기화완료" in q
    assert "(newer_than:2d OR label:카드동기화대기)" in q      # 보류분은 2일이 지나도 다시 본다


OCT = _sms("[Web발신]", "현대 Amex Gold 승인", "신*재", "3,000원 일시불",
           "10/01 09:00", "어딘가", "누적1원")


def test_missing_tab_of_a_near_month_is_created_from_the_template(monkeypatch):
    # 지난달~다음 달 탭이 없으면 샘플을 복사해 만들고 바로 기록한다(오늘 9/22 → 10월은 '다음 달')
    g = FakeGmail()
    args = _wire(monkeypatch, g, {"oct": OCT, "oct2": OCT})
    made = []
    monkeypatch.setattr(mod, "create_month_tab", lambda s, tab, month: made.append((tab, month)) or 77)
    result = mod.do_work({}, args, lambda m: None)
    assert made == [("2026년 10월", 10)]                      # 한 번만 만든다
    assert result["counts"] == {"new": 2, "replaced": 0, "skip": 0, "wait": 0, "failed": 0}
    assert result["lines"][0].startswith("[탭 생성] '2026년 10월'")
    assert "새 탭 1" in result["tasks"]["sheet"][1]
    assert sorted(g.labeled) == [("oct", ("L1",)), ("oct2", ("L1",))]


def test_no_template_tab_means_pending(monkeypatch):
    g = FakeGmail()
    args = _wire(monkeypatch, g, {"oct": OCT})
    monkeypatch.setattr(mod, "create_month_tab", lambda s, tab, month: None)
    result = mod.do_work({}, args, lambda m: None)
    assert result["counts"]["wait"] == 1 and g.labeled == [("oct", ("P1",))]


def test_far_month_is_never_created(monkeypatch):
    # 문자를 잘못 읽어 먼 달이 나오면 탭을 만들지 않고 대기로 둔다
    g = FakeGmail()
    args = _wire(monkeypatch, g, {"dec": DEC})
    monkeypatch.setattr(mod, "create_month_tab", lambda *a: (_ for _ in ()).throw(AssertionError("만들면 안 됨")))
    result = mod.do_work({}, args, lambda m: None)
    assert result["counts"]["wait"] == 1


def test_dry_run_only_announces_the_new_tab(monkeypatch):
    g = FakeGmail()
    args = _wire(monkeypatch, g, {"oct": OCT}, dry_run=True)
    monkeypatch.setattr(mod, "create_month_tab", lambda *a: (_ for _ in ()).throw(AssertionError("시험 실행은 만들지 않는다")))
    result = mod.do_work({}, args, lambda m: None)
    assert result["lines"][0].startswith("[예정] '2026년 10월' 탭 만들기")
    assert result["counts"]["new"] == 1 and g.labeled == []


def test_creatable_months_and_create_request():
    assert mod.creatable_months(dt.date(2026, 9, 30)) == {"2026-08", "2026-09", "2026-10"}
    assert mod.creatable_months(dt.date(2026, 1, 5)) == {"2025-12", "2026-01", "2026-02"}
    assert mod.creatable_months(dt.date(2026, 12, 31)) == {"2026-11", "2026-12", "2027-01"}

    calls = []

    class _Exec:
        def __init__(self, out):
            self.out = out

        def execute(self):
            return self.out

    class _Values:
        def update(self, **kw):
            calls.append(("update", kw["range"], kw["body"]["values"]))
            return _Exec({})

    class _Sheets:
        def spreadsheets(self):
            return self

        def get(self, **kw):
            return _Exec({"sheets": [{"properties": {"title": "지출내역", "sheetId": 1, "index": 0}},
                                     {"properties": {"title": mod.TEMPLATE_TAB, "sheetId": 5, "index": 1}}]})

        def batchUpdate(self, spreadsheetId, body):
            calls.append(("dup", body["requests"][0]["duplicateSheet"]))
            return _Exec({"replies": [{"duplicateSheet": {"properties": {"sheetId": 99}}}]})

        def values(self):
            return _Values()

    assert mod.create_month_tab(_Sheets(), "2026년 10월", 10) == 99
    assert calls[0] == ("dup", {"sourceSheetId": 5, "insertSheetIndex": 2, "newSheetName": "2026년 10월"})
    assert calls[1] == ("update", "'2026년 10월'!D3", [["10월"]])
