import json

import yaml

import collect_minutes
from record_site import Committee, Meeting, Session


class FakeSite:
    def __init__(self):
        self.downloaded = []

    def committees(self, th, cls):
        return [Committee("AS", "재정경제기획위원회")] if cls == 2 else []

    def sessions(self, th, cls, code):
        return [Session("438", "제438회")]

    def meetings(self, th, cls, code, key):
        return [Meeting(57155, "재정경제기획위원회 제1차 (2026. 08. 20.)", True, True),
                Meeting(57000, "재정경제기획위원회 제0차", False, False)]

    def download_pdf(self, minutes_id):
        self.downloaded.append(minutes_id)
        return "제22대국회 제438회 제1차 재정경제기획위원회(전체회의) (2026.08.20.).pdf", b"%PDF-1.4 x"


def write_config(tmp_path):
    cfg = dict(drive_root=str(tmp_path / "root"), current_th=22, recent_sessions=2,
               request_delay=0, retries=1, timeout=5, min_free_gb=0)
    p = tmp_path / "config.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return p


def test_dry_run_downloads_nothing(tmp_path, capsys):
    site = FakeSite()
    code = collect_minutes.run(["--daily", "--dry-run", "--config", str(write_config(tmp_path))], site=site)
    assert code == 0
    assert site.downloaded == []
    out = capsys.readouterr().out
    assert "57155" in out and "[받을 예정]" in out
    assert not (tmp_path / "root" / "_manifest.json").exists()


def test_daily_downloads_new_and_skips_second_time(tmp_path):
    site = FakeSite()
    cfg = str(write_config(tmp_path))
    assert collect_minutes.run(["--daily", "--config", cfg], site=site) == 0
    assert site.downloaded == [57155]
    manifest = json.loads((tmp_path / "root" / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["57155"]["status"] == "ok"
    assert manifest["57000"]["status"] == "no_pdf"
    saved = tmp_path / "root" / manifest["57155"]["path"]
    assert saved.read_bytes().startswith(b"%PDF")
    assert collect_minutes.run(["--daily", "--config", cfg], site=site) == 0
    assert site.downloaded == [57155]            # 두 번째 실행은 받지 않음
    log = (tmp_path / "root" / "_수집로그.md").read_text(encoding="utf-8")
    assert log.count("## ") == 2


def test_backfill_with_limit_stops_early(tmp_path):
    site = FakeSite()
    assert collect_minutes.run(["--backfill", "22", "--limit", "1", "--config", str(write_config(tmp_path))], site=site) == 0
    assert site.downloaded == [57155]


def test_month_prefixes():
    from datetime import date
    assert collect_minutes.month_prefixes(3, date(2026, 1, 15)) == ["2026-01", "2025-12", "2025-11"]


class FakeOpenApi:
    def __init__(self):
        self.calls = []

    def entries(self, th, prefix):
        from catalog import MinutesEntry
        self.calls.append(prefix)
        if prefix != collect_minutes.month_prefixes(1)[0]:
            return []
        return [MinutesEntry(id=57239, th=22, cls=2, committee="정무위원회", sess="439",
                             title="제22대 제439회 제1차 정무위원회", temp=None, has_pdf=True)]


class AuditSite(FakeSite):
    """국감(5)만 있는 사이트 + 임시 재확인 응답."""

    def committees(self, th, cls):
        if cls == 5:
            return [Committee("AG", "과학기술정보방송통신위원회")]
        if cls == 2:
            return [Committee("AC", "정무위원회")]
        return []

    def sessions(self, th, cls, code):
        return [Session("2025", "2025")]

    def meetings(self, th, cls, code, key):
        if cls == 5:
            return [Meeting(55553, "국정감사 (2025. 10. 30.)", False, True)]
        if cls == 2 and key == "439":
            return [Meeting(57239, "정무위원회 제1차 (2026. 09. 03.)", False, True)]   # 확정본
        return []


def test_daily_reports_status_when_configured(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(collect_minutes, "report_status", lambda repo, **kw: calls.append((repo, kw)) or True)
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(dict(drive_root=str(tmp_path / "root"), current_th=22, recent_sessions=2,
                                       request_delay=0, retries=1, timeout=5, min_free_gb=0,
                                       office_repo=str(tmp_path / "site"), drive_link="https://drive/x"),
                                  allow_unicode=True), encoding="utf-8")
    assert collect_minutes.run(["--daily", "--config", str(cfg)], site=FakeSite()) == 0
    assert len(calls) == 1
    repo, kw = calls[0]
    assert repo == str(tmp_path / "site")
    assert kw["automation_id"] == "minutes" and kw["dept"] == "research" and kw["ok"] is True
    assert kw["counts"]["new"] == 1 and kw["counts"]["total"] == 1
    assert kw["link"] == "https://drive/x"


def test_dry_run_never_reports(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(collect_minutes, "report_status", lambda repo, **kw: calls.append(1))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(dict(drive_root=str(tmp_path / "root"), current_th=22, recent_sessions=2,
                                       request_delay=0, retries=1, timeout=5, min_free_gb=0,
                                       office_repo=str(tmp_path / "site")), allow_unicode=True), encoding="utf-8")
    assert collect_minutes.run(["--daily", "--dry-run", "--config", str(cfg)], site=FakeSite()) == 0
    assert calls == []


def test_daily_with_open_api_uses_api_then_site_for_audit_and_recheck(tmp_path):
    site, api = AuditSite(), FakeOpenApi()
    cfg = str(write_config(tmp_path))
    assert collect_minutes.run(["--daily", "--config", cfg], site=site, api=api) == 0
    assert len(api.calls) == 2                                  # 기본 2개월
    # 1차: API로 57239(임시로 간주) 수신, 국감 55553 수신, 재확인에서 확정본 발견 → 교체
    assert site.downloaded == [57239, 55553, 57239]
    manifest = json.loads((tmp_path / "root" / "_manifest.json").read_text(encoding="utf-8"))
    assert manifest["57239"]["temp"] is False
    assert manifest["55553"]["cls"] == 5
    # 2차: 아무것도 받지 않음
    site.downloaded.clear()
    assert collect_minutes.run(["--daily", "--config", cfg], site=site, api=api) == 0
    assert site.downloaded == []


def test_drive_storage_uses_drive_client(tmp_path):
    from tests.test_drive_store import FakeDrive
    drive = FakeDrive()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(dict(storage="drive", drive_folder_id="root", current_th=22, recent_sessions=2,
                                       request_delay=0, retries=1, timeout=5, min_free_gb=0), allow_unicode=True),
                   encoding="utf-8")
    site = FakeSite()
    assert collect_minutes.run(["--daily", "--config", str(cfg)], site=site, drive_client=drive) == 0
    assert site.downloaded == [57155]
    names = [f["name"] for f in drive.files.values()]
    assert "_manifest.json" in names and "_수집로그.md" in names
    assert any(n.endswith(".pdf") for n in names)


def test_open_api_key_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPEN_API_KEY", "envkey")
    captured = {}
    monkeypatch.setattr(collect_minutes, "OpenApi", lambda key, timeout: (captured.__setitem__("key", key), FakeOpenApi())[1])
    cfg = str(write_config(tmp_path))
    assert collect_minutes.run(["--daily", "--dry-run", "--config", cfg], site=AuditSite()) == 0
    assert captured["key"] == "envkey"
