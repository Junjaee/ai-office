from pathlib import Path

from catalog import MinutesEntry
from store import LocalDriveStore, sanitize


def entry(**kw):
    base = dict(id=57155, th=22, cls=2, committee="재정경제기획위원회", sess="438",
                title="재정경제기획위원회 제1차 (2026. 08. 20.)", temp=True, has_pdf=True)
    base.update(kw)
    return MinutesEntry(**base)


def test_sanitize_replaces_windows_forbidden_chars():
    assert sanitize('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"
    assert sanitize("  국토교통위원회 ") == "국토교통위원회"


def test_relative_path_for_committee(tmp_path):
    store = LocalDriveStore(tmp_path)
    rel = store.relative_path(entry(), "제22대국회 제438회(임시회) 제1차 재정경제기획위원회(전체회의) (2026.08.20.).pdf")
    assert rel == Path("제22대/상임위원회/재정경제기획위원회/제22대국회 제438회(임시회) 제1차 재정경제기획위원회(전체회의) (2026.08.20.).pdf")


def test_relative_path_for_plenary_and_audit(tmp_path):
    store = LocalDriveStore(tmp_path)
    assert store.relative_path(entry(cls=1, committee="국회본회의", sess="439"), "x.pdf") == Path("제22대/국회본회의/x.pdf")
    assert store.relative_path(entry(cls=4, committee="예산결산특별위원회"), "x.pdf") == Path("제22대/예산결산특별위원회/x.pdf")
    assert store.relative_path(entry(cls=5, committee="과학기술정보방송통신위원회", sess="2025"), "x.pdf") == Path("제22대/국정감사/과학기술정보방송통신위원회/2025/x.pdf")


def test_fallback_filename_when_missing(tmp_path):
    store = LocalDriveStore(tmp_path)
    assert store.relative_path(entry(), None).name == "제22대_상임위원회_재정경제기획위원회_57155.pdf"


def test_save_pdf_writes_file_and_returns_size(tmp_path):
    store = LocalDriveStore(tmp_path)
    rel = Path("제22대/국회본회의/a.pdf")
    size = store.save_pdf(rel, b"%PDF-1.4 hello")
    assert size == 14
    assert (tmp_path / rel).read_bytes() == b"%PDF-1.4 hello"


def test_manifest_roundtrip_and_atomic_save(tmp_path):
    store = LocalDriveStore(tmp_path)
    assert store.manifest == {}
    store.record(entry(), status="ok", path="제22대/상임위원회/재정경제기획위원회/a.pdf", size=10)
    store.save_manifest()
    again = LocalDriveStore(tmp_path)
    assert again.manifest["57155"]["temp"] is True
    assert again.manifest["57155"]["status"] == "ok"
    assert again.manifest["57155"]["path"].endswith("a.pdf")
    assert not list(tmp_path.glob("*.tmp"))


def test_needs_download_rules(tmp_path):
    store = LocalDriveStore(tmp_path)
    e = entry()
    assert store.needs_download(e) is True                      # 처음 보는 id
    store.record(e, status="ok", path="p", size=1)
    assert store.needs_download(e) is False                     # 이미 받음, 임시 상태 동일
    assert store.needs_download(entry(temp=False)) is True      # 임시 → 확정
    store.record(entry(temp=False), status="ok", path="p", size=1)
    assert store.needs_download(entry(temp=True)) is False      # 확정본 있는데 임시로 보이면 무시
    store.record(entry(id=1, has_pdf=False), status="no_pdf", path=None, size=0)
    assert store.needs_download(entry(id=1, has_pdf=False)) is False
    assert store.needs_download(entry(id=1, has_pdf=True)) is True   # PDF가 생기면 다시 시도
    store.record(entry(id=2), status="error", path=None, size=0)
    assert store.needs_download(entry(id=2)) is True            # 실패는 재시도


def test_unknown_temp_from_open_api(tmp_path):
    store = LocalDriveStore(tmp_path)
    api_entry = entry(id=9, temp=None)
    assert store.needs_download(api_entry) is True               # 처음 보는 id
    store.record(api_entry, status="ok", path="p", size=1)
    assert store.manifest["9"]["temp"] is True                   # 모르면 임시로 간주
    assert store.needs_download(api_entry) is False              # API만으로는 재다운로드하지 않음
    assert store.needs_download(entry(id=9, temp=False)) is True  # 사이트에서 확정 확인되면 교체
    store.record(entry(id=9, temp=False), status="ok", path="p", size=1)
    store.record(entry(id=9, temp=None), status="ok", path="p", size=1)
    assert store.manifest["9"]["temp"] is False                  # None은 이전 값 유지


def test_pending_temp_lists_only_temp_ok_entries(tmp_path):
    store = LocalDriveStore(tmp_path)
    store.record(entry(id=1, temp=True), status="ok", path="p", size=1)
    store.record(entry(id=2, temp=False), status="ok", path="p", size=1)
    store.record(entry(id=3, temp=True, cls=5, sess="2025"), status="ok", path="p", size=1)
    store.record(entry(id=4, temp=True), status="error", path=None, size=0)
    assert [v["title"] for v in store.pending_temp(22)] and {v["cls"] for v in store.pending_temp(22)} == {2}
    assert len(store.pending_temp(22)) == 1


def test_log_run_appends_markdown(tmp_path):
    store = LocalDriveStore(tmp_path)
    store.log_run("daily", ["신규 1건, 교체 0건, 실패 0건", "[신규] 제22대/국회본회의/a.pdf"])
    text = (tmp_path / "_수집로그.md").read_text(encoding="utf-8")
    assert "(daily)" in text and "[신규] 제22대/국회본회의/a.pdf" in text
