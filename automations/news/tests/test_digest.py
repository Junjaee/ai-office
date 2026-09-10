"""중복 합치기·묶음 정리·마크다운 만들기 — 전부 순수 함수라 네트워크가 필요 없다."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import news_digest as d  # noqa: E402
from google_news import Article  # noqa: E402
from news_store import day_path  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 10, 15, 0, tzinfo=KST)


def art(title, link, source, published="2026-09-10T11:00:00+09:00", query="이준석", group="의원 관련"):
    return Article(title=title, link=link, source=source, published=published, query=query, group=group)


def test_dedupe_merges_same_title_from_different_media():
    items = d.dedupe([
        art('천하람 "사퇴하라"', "https://a", "연합뉴스"),
        art("천하람 사퇴하라", "https://b", "머니투데이", query="개혁신당"),   # 기호만 다름 = 같은 기사
        art("다른 기사", "https://c", "한겨레"),
    ])
    assert len(items) == 2
    merged = items[0]
    assert merged["sources"] == ["연합뉴스", "머니투데이"]
    assert merged["queries"] == ["이준석", "개혁신당"]
    assert merged["link"] == "https://a"          # 먼저 본 기사를 대표로 둔다


def test_dedupe_keeps_earliest_published_time():
    items = d.dedupe([
        art("같은 기사", "https://a", "A", published="2026-09-10T11:00:00+09:00"),
        art("같은 기사", "https://b", "B", published="2026-09-10T09:00:00+09:00"),
    ])
    assert items[0]["published"] == "2026-09-10T09:00:00+09:00"


def test_merge_manifest_returns_only_new_and_adds_sources_to_old():
    manifest = {}
    first = d.merge_manifest(manifest, d.dedupe([art("기사", "https://a", "연합뉴스")]), now=NOW)
    assert len(first) == 1 and first[0]["day"] == "2026-09-10"

    again = d.merge_manifest(manifest, d.dedupe([art("기사", "https://a", "한겨레")]), now=NOW)
    assert again == []                                  # 이미 본 기사는 신규가 아니다
    assert manifest[next(iter(manifest))]["sources"] == ["연합뉴스", "한겨레"]


def test_prune_manifest_drops_old_days_only():
    manifest = {"old": {"day": "2026-06-01"}, "new": {"day": "2026-09-09"}}
    assert d.prune_manifest(manifest, keep_days=60, now=NOW) == 1
    assert list(manifest) == ["new"]


def test_entries_for_day_is_newest_first():
    manifest = {
        "a": {"day": "2026-09-10", "published": "2026-09-10T09:00:00+09:00"},
        "b": {"day": "2026-09-10", "published": "2026-09-10T14:00:00+09:00"},
        "c": {"day": "2026-09-09", "published": "2026-09-09T14:00:00+09:00"},
    }
    assert [r["published"][11:16] for r in d.entries_for_day(manifest, "2026-09-10")] == ["14:00", "09:00"]


def test_render_day_splits_groups_and_marks_empty_one():
    rows = d.merge_manifest({}, d.dedupe([
        art("의원 기사", "https://a", "연합뉴스", group="의원 관련"),
    ]), now=NOW)
    page = d.render_day("2026-09-10", rows, ["의원 관련", "위원회 동향"], updated_at="2026-09-10 15:00")
    assert "# 2026-09-10 기사 모니터링" in page
    assert "## 의원 관련 (1건)" in page
    assert "## 위원회 동향 (0건)" in page
    assert "_새 기사가 없습니다._" in page
    assert "[의원 기사](https://a) — 연합뉴스" in page
    assert "`11:00`" in page


def test_media_counts_is_sorted_by_count():
    rows = [{"sources": ["연합뉴스", "한겨레"]}, {"sources": ["연합뉴스"]}]
    assert d.media_counts(rows) == [("연합뉴스", 2), ("한겨레", 1)]


def test_day_path_is_year_month_folders():
    assert str(day_path("2026-09-10")).replace("\\", "/") == "2026/2026-09/2026-09-10.md"


def test_render_day_shows_date_for_articles_from_earlier_days():
    rows = d.merge_manifest({}, d.dedupe([
        art("어제 기사", "https://a", "연합뉴스", published="2026-09-09T22:16:00+09:00"),
        art("오늘 기사", "https://b", "한겨레", published="2026-09-10T11:00:00+09:00"),
    ]), now=NOW)
    page = d.render_day("2026-09-10", rows, ["의원 관련"], updated_at="2026-09-10 15:00")
    assert "`09-09 22:16`" in page      # 다른 날 기사는 날짜까지
    assert "`11:00`" in page            # 오늘 기사는 시:분만
