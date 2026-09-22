"""상임위 메일 — do_work 흐름(찾기 → 알림 → 라벨 정리). 가짜 지메일·가짜 텔레그램, 네트워크 없음."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))
import run_mail  # noqa: E402

CFG = {
    "committees": [{"label": "재경위", "query": "from:fec@assembly.go.kr", "folder_id": "FOLDER-재경위"},
                   {"label": "예결위", "query": "from:assembly.go.kr {예결위}"}],   # 예결위는 저장 폴더 없음
    "lookback_days": 7, "max_per_run": 20, "tasks": ["check", "notify"],
}


def message(mid, subject, ts, label_ids=("INBOX",)):
    return {"id": mid, "threadId": f"th-{mid}", "internalDate": str(ts), "labelIds": list(label_ids),
            "payload": {"headers": [{"name": "Subject", "value": subject},
                                    {"name": "From", "value": '"재정경제기획위원회" <fec@assembly.go.kr>'},
                                    {"name": "Date", "value": "Wed, 16 Sep 2026 09:41:59 +0900"}],
                        "parts": [{"filename": "의사일정(안).hwp",
                                   "body": {"size": 1000, "attachmentId": f"att-{mid}"}}]}}


class FakeGmail:
    """users().messages().list/get/modify 와 users().labels().list/create 만 흉내 낸다."""

    def __init__(self, by_query, labels=()):
        self.by_query = by_query                      # 검색어 일부 → 메시지 목록
        self.label_rows = [{"id": f"L{i}", "name": n} for i, n in enumerate(labels)]
        self.modified: list[tuple] = []
        self.created: list[str] = []
        self.queries: list[str] = []
        self.downloaded: list[tuple] = []
        self.fail_modify_for: set = set()

    # 체이닝 흉내
    def users(self):
        return self

    def messages(self):
        return self

    def labels(self):
        return _Labels(self)

    def list(self, userId=None, q=None, maxResults=None):
        self.queries.append(q)
        hit = [m for key, ms in self.by_query.items() if key in q for m in ms]
        return _Exec({"messages": [{"id": m["id"]} for m in hit]})

    def get(self, userId=None, id=None, format=None):
        found = [m for ms in self.by_query.values() for m in ms if m["id"] == id]
        return _Exec(found[0])

    def attachments(self):
        return _Attachments(self)

    def modify(self, userId=None, id=None, body=None):
        if id in self.fail_modify_for:
            from googleapiclient.errors import HttpError
            raise HttpError(type("R", (), {"status": 403, "reason": "forbidden"})(), b"{}")
        self.modified.append((id, tuple(body["addLabelIds"]), tuple(body["removeLabelIds"])))
        return _Exec({})


class _Attachments:
    def __init__(self, gmail):
        self.g = gmail

    def get(self, userId=None, messageId=None, id=None):
        import base64
        self.g.downloaded.append((messageId, id))
        return _Exec({"data": base64.urlsafe_b64encode(b"HWP-CONTENT").decode()})


class _Labels:
    def __init__(self, gmail):
        self.g = gmail

    def list(self, userId=None):
        return _Exec({"labels": self.g.label_rows})

    def create(self, userId=None, body=None):
        self.g.created.append(body["name"])
        made = {"id": f"NEW-{body['name']}", "name": body["name"]}
        self.g.label_rows.append(made)
        return _Exec(made)


class _Exec:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class FakeSend:
    def __init__(self):
        self.sent = []

    def __call__(self, token, chat, text, **kw):
        self.sent.append((chat, text))
        return {}


class FakeDrive:
    """DriveClient 흉내 — 올린 것과 이미 있는 것만 기억한다."""

    def __init__(self, existing=()):
        self.uploaded = []                       # (폴더, 이름, 바이트, mime)
        self.existing = set(existing)            # (폴더, 이름)

    def find(self, parent_id, name):
        return {"id": "old"} if (parent_id, name) in self.existing else None

    def upload(self, parent_id, name, data, mime, file_id=None):
        self.uploaded.append((parent_id, name, data, mime))
        return "new-id"


class FakeSendDoc:
    def __init__(self):
        self.files = []

    def __call__(self, token, chat, filename, data, **kw):
        self.files.append((chat, filename, data))
        return {}


def setup(monkeypatch, gmail, *, chat="9999", existing=()):
    sent = FakeSend()
    asked = []
    monkeypatch.setattr(run_mail, "gmail_service", lambda: gmail)
    monkeypatch.setattr(run_mail, "send_message", sent)
    docs = FakeSendDoc()
    monkeypatch.setattr(run_mail, "send_document", docs)
    sent.docs = docs
    drive = FakeDrive(existing=existing)
    monkeypatch.setattr(run_mail, "DriveClient", lambda: drive)
    sent.drive = drive
    monkeypatch.setattr(run_mail, "telegram_env",
                        lambda chat_key, token_key: (asked.append((chat_key, token_key)), ("tok", chat))[1])
    sent.asked = asked
    return sent


def work(dry_run=False):
    return argparse.Namespace(dry_run=dry_run, config="")


def test_finds_notifies_and_files_new_mail(monkeypatch):
    gmail = FakeGmail({"fec@assembly.go.kr": [message("m1", "의사일정(안) 송부", 100)],
                       "{예결위}": [message("m2", "예결위 자료", 50)]})
    sent = setup(monkeypatch, gmail)

    out = run_mail.do_work(CFG, work(), lambda m: None)

    # 두 위원회를 합쳐 받은 시각 순(오래된 것 먼저)으로 한 번에 알린다
    assert len(sent.sent) == 1
    # 캘린더 봇이 아니라 메일 전용 봇으로 보낸다 (사용자 결정 2026-09-17)
    assert sent.asked == [("NOTICE_530_CHAT_ID", "NOTICE_530_BOT_TOKEN")]
    chat, text = sent.sent[0]
    assert chat == "9999"
    assert text.index("예결위 자료") < text.index("의사일정(안) 송부")
    # 라벨을 붙이고 받은편지함에서 뺀다
    assert sorted(gmail.created) == ["예결위", "재경위"]
    assert {(mid, rem) for mid, _add, rem in gmail.modified} == {("m1", ("INBOX",)), ("m2", ("INBOX",))}
    # 첨부도 파일로 보낸다 (사용자 결정 2026-09-17)
    assert [f[1] for f in sent.docs.files] == ["의사일정(안).hwp", "의사일정(안).hwp"]
    assert sent.docs.files[0][2] == b"HWP-CONTENT"
    # 재경위 첨부만 드라이브 수신함에 저장한다(예결위는 folder_id 가 없다) — 사용자 결정 2026-09-17
    assert [(f[0], f[1]) for f in sent.drive.uploaded] == [("FOLDER-재경위", "의사일정(안).hwp")]
    assert sent.drive.uploaded[0][2] == b"HWP-CONTENT"
    assert out["counts"] == {"new": 2, "sent": 1, "failed": 0, "files": 2, "saved": 1}
    assert out["lines"] == ["재경위 1건", "예결위 1건"]      # 제목 없음 (공개 저장소)
    assert out["tasks"]["notify"] == (True, "알림 2건, 정리 2건, 첨부 2개(드라이브 1개)")


def test_existing_label_is_reused_and_query_skips_labelled(monkeypatch):
    gmail = FakeGmail({"fec@assembly.go.kr": [message("m1", "의사일정", 100)]}, labels=["재경위"])
    setup(monkeypatch, gmail)

    run_mail.do_work(CFG, work(), lambda m: None)

    assert gmail.created == []                                   # 이미 있는 라벨은 새로 만들지 않는다
    assert gmail.modified[0][1] == ("L0",)
    assert all('-label:"재경위"' in q for q in gmail.queries if "fec@" in q)


def test_no_new_mail_skips_report_and_sends_nothing(monkeypatch):
    gmail = FakeGmail({})
    sent = setup(monkeypatch, gmail)

    out = run_mail.do_work(CFG, work(), lambda m: None)

    assert sent.sent == [] and gmail.modified == []
    assert out["skip_report"] is True                              # 5분마다 도니 빈 실행은 커밋하지 않는다
    assert out["tasks"] == {"check": (True, "새 메일 0건"), "notify": (True, "보낼 것 없음")}


def test_dry_run_sends_nothing_and_keeps_inbox(monkeypatch):
    gmail = FakeGmail({"fec@assembly.go.kr": [message("m1", "의사일정", 100)]})
    sent = setup(monkeypatch, gmail)

    out = run_mail.do_work(CFG, work(dry_run=True), lambda m: None)

    assert sent.sent == [] and sent.docs.files == [] and gmail.modified == [] and gmail.created == []
    assert out["counts"] == {"new": 1, "sent": 0}
    assert out["tasks"]["notify"] == (True, "시험 실행 — 보내지 않음")


def test_label_failure_is_reported_but_keeps_going(monkeypatch):
    gmail = FakeGmail({"fec@assembly.go.kr": [message("m1", "가", 100), message("m2", "나", 200)]})
    gmail.fail_modify_for = {"m1"}
    setup(monkeypatch, gmail)

    out = run_mail.do_work(CFG, work(), lambda m: None)

    assert [mid for mid, _a, _r in gmail.modified] == ["m2"]
    assert out["counts"]["failed"] == 1
    assert out["tasks"]["notify"] == (False, "알림 2건, 정리 1건, 첨부 2개(드라이브 2개)")


def test_big_attachment_is_skipped_with_a_note(monkeypatch):
    """텔레그램 업로드 한도를 넘는 파일은 그 파일만 건너뛰고 알린다."""
    msg = message("m1", "큰 자료", 100)
    msg["payload"]["parts"][0]["body"] = {"size": 60 * 1024 * 1024, "attachmentId": "big"}
    gmail = FakeGmail({"fec@assembly.go.kr": [msg]})
    sent = setup(monkeypatch, gmail)

    out = run_mail.do_work({**CFG, "max_attachment_mb": 45}, work(), lambda m: None)

    assert sent.docs.files == []                       # 텔레그램으로는 못 보내지만
    assert [f[1] for f in sent.drive.uploaded] == ["의사일정(안).hwp"]   # 드라이브에는 저장된다
    assert "보내지 못했어요" in sent.sent[-1][1]
    assert out["tasks"]["notify"][0] is True          # 알림·정리 자체는 성공


def test_attachments_can_be_turned_off(monkeypatch):
    gmail = FakeGmail({"fec@assembly.go.kr": [message("m1", "의사일정", 100)]})
    sent = setup(monkeypatch, gmail)

    out = run_mail.do_work({**CFG, "send_attachments": False}, work(), lambda m: None)

    assert sent.docs.files == []
    assert [f[1] for f in sent.drive.uploaded] == ["의사일정(안).hwp"]   # 드라이브 저장은 계속
    assert "의사일정(안).hwp" in sent.sent[0][1]      # 대신 글에 파일 이름이 남는다


def test_same_file_is_not_uploaded_twice(monkeypatch):
    """같은 자료가 여러 메일에 붙어 오므로, 수신함에 같은 이름이 있으면 건너뛴다."""
    gmail = FakeGmail({"fec@assembly.go.kr": [message("m1", "자료 재송부", 100)]})
    sent = setup(monkeypatch, gmail, existing=[("FOLDER-재경위", "의사일정(안).hwp")])

    out = run_mail.do_work(CFG, work(), lambda m: None)

    assert sent.drive.uploaded == []
    assert out["counts"]["saved"] == 0
    assert [f[1] for f in sent.docs.files] == ["의사일정(안).hwp"]   # 텔레그램으로는 그대로 온다


def test_gmail_error_becomes_korean_message(monkeypatch):
    from googleapiclient.errors import HttpError

    class Broken(FakeGmail):
        def list(self, userId=None, q=None, maxResults=None):
            raise HttpError(type("R", (), {"status": 403, "reason": "insufficient"})(), b"{}")

    setup(monkeypatch, Broken({}))
    import pytest
    with pytest.raises(RuntimeError, match="메일 읽기 실패: HTTP 403"):
        run_mail.do_work(CFG, work(), lambda m: None)
