"""run_news.py — 뼈대의 보고 규칙과 do_work 의 실제 흐름을 확인한다 (네트워크·드라이브 없이)."""
import sys
from pathlib import PurePosixPath
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_news as mod  # noqa: E402
from google_news import Article  # noqa: E402


@pytest.fixture
def cfg_file(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text('office_repo: "."\noffice_workspace: "assembly"\nnext_run: "3시간마다"\ntasks: [collect, digest]\n',
                 encoding="utf-8")
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
                "tasks": {"collect": (True, "신규 2건"), "digest": (True, "오늘 10건")}}

    assert mod.run(["--config", cfg_file], work=work) == 0
    r = reports[0]
    assert r["ok"] is True
    assert r["counts"]["total"] == 10
    assert r["tasks"] == [{"id": "collect", "status": "done", "summary": "신규 2건"},
                          {"id": "digest", "status": "done", "summary": "오늘 10건"}]
    assert r["summary"].startswith("신규 2건, 실패 0건")
    assert r["workspace"] == "assembly"


def test_exception_reports_korean_failure(cfg_file, reports):
    def work(cfg, args, progress):
        raise RuntimeError("뉴스 요청 실패: 붐")

    assert mod.run(["--config", cfg_file], work=work) == 1
    assert reports[0]["ok"] is False
    assert reports[0]["summary"] == "뉴스 목록을 받아오지 못했어요"


def test_dry_run_never_reports(cfg_file, reports):
    def work(cfg, args, progress):
        assert args.dry_run
        return {"counts": {"new": 0}, "lines": [], "tasks": {}}

    assert mod.run(["--config", cfg_file, "--dry-run"], work=work) == 0
    assert reports == []


# ───────────────────────── do_work 자체 ─────────────────────────

CFG = {
    "queries": [{"q": "이준석", "group": "의원 관련"}, {"q": "재경위", "group": "위원회 동향"}],
    "manifest_days": 60, "tasks": ["collect", "digest"],
}


class FakeNews:
    """검색어별로 미리 정한 기사를 돌려준다. 검색어가 FAILS 에 있으면 실패한다."""
    FAILS: set = set()
    RESULT: dict = {}

    def __init__(self, **kw):
        pass

    def fetch(self, query, *, group="", days=1):
        if query in self.FAILS:
            raise RuntimeError(f"뉴스 요청 실패: '{query}'")
        return [Article(query=query, group=group, **a) for a in self.RESULT.get(query, [])]


class FakeStore:
    def __init__(self):
        self.files: dict[str, str] = {}

    def load_manifest(self):
        import json
        return json.loads(self.files["_manifest.json"]) if "_manifest.json" in self.files else {}

    def save_manifest(self, m):
        import json
        self.files["_manifest.json"] = json.dumps(m, ensure_ascii=False)

    def write_text(self, rel, text):
        self.files[str(PurePosixPath(str(rel)).as_posix())] = text


def article(title, link, source="연합뉴스", published="2026-09-10T11:00:00+09:00"):
    return {"title": title, "link": link, "source": source, "published": published}


class Args:
    dry_run = False


@pytest.fixture
def fake_news(monkeypatch):
    FakeNews.FAILS = set()
    FakeNews.RESULT = {"이준석": [article("의원 기사", "https://a")],
                       "재경위": [article("재경위 기사", "https://b", source="한겨레")]}
    monkeypatch.setattr(mod, "GoogleNews", FakeNews)
    return FakeNews


def test_do_work_saves_day_file_and_counts_new(fake_news, monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(mod, "open_store", lambda cfg: store)

    result = mod.do_work(CFG, Args(), lambda m: None)

    assert result["counts"]["new"] == 2
    assert result["counts"]["failed"] == 0
    assert result["counts"]["total"] == 2
    page = next(v for k, v in store.files.items() if k.endswith(".md"))
    assert "## 의원 관련 (1건)" in page and "## 위원회 동향 (1건)" in page
    assert "[의원 기사](https://a)" in page
    assert result["tasks"]["collect"][0] is True
    assert result["tasks"]["digest"][0] is True


def test_do_work_second_run_finds_no_new_article(fake_news, monkeypatch):
    store = FakeStore()
    monkeypatch.setattr(mod, "open_store", lambda cfg: store)

    mod.do_work(CFG, Args(), lambda m: None)
    result = mod.do_work(CFG, Args(), lambda m: None)

    assert result["counts"]["new"] == 0        # 같은 기사를 다시 세지 않는다
    assert result["counts"]["total"] == 2


def test_do_work_one_failed_query_keeps_going_but_marks_collect_error(fake_news, monkeypatch):
    fake_news.FAILS = {"재경위"}
    monkeypatch.setattr(mod, "open_store", lambda cfg: FakeStore())

    result = mod.do_work(CFG, Args(), lambda m: None)

    assert result["counts"]["new"] == 1
    assert result["counts"]["failed"] == 1
    assert result["tasks"]["collect"][0] is False
    assert any("[실패] 재경위" in ln for ln in result["lines"])


def test_do_work_all_queries_failed_raises(fake_news, monkeypatch):
    fake_news.FAILS = {"이준석", "재경위"}
    monkeypatch.setattr(mod, "open_store", lambda cfg: FakeStore())

    with pytest.raises(RuntimeError, match="뉴스 요청 실패"):
        mod.do_work(CFG, Args(), lambda m: None)


def test_do_work_dry_run_does_not_open_store(fake_news, monkeypatch):
    monkeypatch.setattr(mod, "open_store", lambda cfg: pytest.fail("dry-run 은 저장소를 열면 안 된다"))

    args = Args()
    args.dry_run = True
    result = mod.do_work(CFG, args, lambda m: None)

    assert result["counts"]["new"] == 2
