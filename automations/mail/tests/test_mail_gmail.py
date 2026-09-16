"""상임위 메일 — 검색어·알림 글·안전한 기록 (순수 함수, 네트워크 없음)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mail_gmail import (  # noqa: E402
    Mail, _clean_sender, _hhmm, build_notice, build_query, describe, safe_lines,
)

RULES = [{"label": "재경위", "query": "from:fec@assembly.go.kr"},
         {"label": "예결위", "query": "from:assembly.go.kr {예결위 예산결산특별위원회}"}]


def test_build_query_excludes_already_labelled_and_old():
    assert build_query(RULES[0], 7) == 'from:fec@assembly.go.kr -label:"재경위" newer_than:7d'
    assert build_query(RULES[1], 0) == 'from:assembly.go.kr {예결위 예산결산특별위원회} -label:"예결위"'
    assert build_query({"query": "from:a@b.c"}, 3) == "from:a@b.c newer_than:3d"


def test_clean_sender_and_time():
    assert _clean_sender('"재정경제기획위원회" <fec@assembly.go.kr>') == "재정경제기획위원회"
    assert _clean_sender("<fec@assembly.go.kr>") == "(보낸사람 없음)"
    assert _hhmm("Wed, 16 Sep 2026 09:41:59 +0900") == "9/16 09:41"
    assert _hhmm("Wed, 16 Sep 2026 00:41:59 +0000") == "9/16 09:41"   # UTC 로 와도 KST 로 보여 준다
    assert _hhmm("이상한 값") == "이상한 값"


def mail(subject="제3차 전체회의 의사일정(안)", label="재경위", files=(), tid="t1"):
    return Mail(id="m1", thread_id=tid, label=label, when="9/16 09:41",
                sender='"재정경제기획위원회" <fec@assembly.go.kr>', subject=subject,
                attachments=tuple(files), ts=1)


def test_describe_shows_subject_sender_attachments_and_link():
    lines = describe(mail(files=("의사일정(안).hwp",)))
    assert lines == [
        "[재경위] 제3차 전체회의 의사일정(안)",
        "· 9/16 09:41  재정경제기획위원회",
        "· 첨부 1개: 의사일정(안).hwp",
        "https://mail.google.com/mail/u/0/#all/t1",
    ]
    assert describe(mail(subject="")) [0] == "[재경위] (제목 없음)"
    assert len(describe(mail())) == 3   # 첨부가 없으면 첨부 줄도 없다


def test_build_notice_counts_and_cuts_to_telegram_limit():
    text = build_notice([mail(), mail(subject="공청회 진술문 송부", label="예결위", tid="t2")])
    assert text.startswith("새 상임위 메일 2건")
    assert "[예결위] 공청회 진술문 송부" in text

    long = [mail(subject="긴 제목 " * 40, tid=f"t{i}") for i in range(40)]
    cut = build_notice(long)
    assert len(cut) <= 4096
    assert cut.endswith("… 너무 길어 일부만 보냈어요")


def test_safe_lines_never_contain_subject_or_sender():
    """저장소가 공개라 상태 파일·일지에는 위원회별 건수만 남긴다 (사용자 결정 2026-09-16)."""
    mails = [mail(), mail(subject="공청회 진술문 송부"), mail(label="예결위")]
    lines = safe_lines(mails, RULES)
    assert lines == ["재경위 2건", "예결위 1건"]
    joined = " ".join(lines)
    for secret in ("의사일정", "공청회", "재정경제기획위원회", "fec@assembly.go.kr", "mail.google.com"):
        assert secret not in joined
    assert safe_lines([], RULES) == ["새 메일 없음"]
