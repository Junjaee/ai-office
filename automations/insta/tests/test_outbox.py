"""완성 릴스 대기열(insta_outbox): 넣기(릴리스 첨부 + 게시 정보), 시각이 된 것만 게시, 게시 기록·DM 키워드, 중복 방지. GitHub·인스타는 가짜로."""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import insta_outbox as ob  # noqa: E402

KST = timezone(timedelta(hours=9))


class FakeGh:
    def __init__(self, release_exists=False):
        self.calls = []
        self.release_exists = release_exists

    def __call__(self, *args, check=True):
        self.calls.append(args)
        if args[:2] == ("release", "view"):
            return subprocess.CompletedProcess(args, 0 if self.release_exists else 1, "", "")
        if args[:2] == ("release", "download"):
            out = Path(args[args.index("-D") + 1])
            out.mkdir(parents=True, exist_ok=True)
            for i, a in enumerate(args):
                if a == "-p":
                    (out / args[i + 1]).write_bytes(b"x")
        return subprocess.CompletedProcess(args, 0, "", "")


class FakePub:
    def __init__(self):
        self.calls = []

    def account_env(self, account):
        return "tok", "uid"

    class Instagram:
        def __init__(self, token, user_id):
            pass

    def upload_public(self, paths, prefix):
        self.calls.append(("upload", [p.name for p in paths]))
        return ["https://r2.test/v.mp4", "https://r2.test/t.jpg"]

    def publish_reel(self, ig, url, caption, cover_url="", progress=print):
        self.calls.append(("publish", url, caption, cover_url))
        return {"media_id": "m1", "permalink": "https://www.instagram.com/reel/abc/"}


def folder(tmp_path, caption="세상에 없는 벼룩시장. 댓글에 '벼룩시장' 남기면 DM"):
    d = tmp_path / "flea"
    d.mkdir()
    (d / "reel.mp4").write_bytes(b"v")
    (d / "thumb.jpg").write_bytes(b"j")
    meta = {"key": "https://www.reddit.com/r/aivideo/comments/x", "title": "t", "hook": "h", "caption": caption, "hashtags": ["#AI영상"],
            "dm_keyword": "벼룩시장", "dm_text": "프롬프트 예시 " * 10, "credit": "Source · u/a / Reddit", "source_url": "https://www.reddit.com/x"}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return d


def test_add_uploads_assets_and_saves_queued_item(tmp_path):
    run = FakeGh(release_exists=False)
    item = ob.add("policy", folder(tmp_path), "2026-09-15T18:30", run=run, root=tmp_path / "data", progress=lambda m: None)
    assert item["status"] == "queued" and item["due"] == "2026-09-15T18:30+09:00" and item["video"].startswith("reel-20260915-1830-")
    assert [c[:2] for c in run.calls] == [("release", "view"), ("release", "create"), ("release", "upload")]
    assert (tmp_path / "data" / "policy" / "outbox" / f"{item['id']}.json").exists()


def test_publish_only_when_due_then_records_and_cleans_up(tmp_path):
    root, run, pub = tmp_path / "data", FakeGh(release_exists=True), FakePub()
    ob.add("policy", folder(tmp_path), "2026-09-15T18:30", run=run, root=root, progress=lambda m: None)
    early = datetime(2026, 9, 15, 18, 0, tzinfo=KST)
    assert ob.publish("policy", now=early, pub=pub, run=run, root=root, workdir=tmp_path / "w", progress=lambda m: None) is None
    assert pub.calls == []
    late = datetime(2026, 9, 15, 18, 31, tzinfo=KST)
    row = ob.publish("policy", now=late, pub=pub, run=run, root=root, workdir=tmp_path / "w", progress=lambda m: None)
    assert row is not None
    assert row["media_id"] == "m1" and row["dm_keyword"] == "벼룩시장" and row["kind"] == "reel_commentary"
    assert pub.calls[1][2].endswith("#AI영상") and pub.calls[1][3] == "https://r2.test/t.jpg"
    assert sum(1 for c in run.calls if c[:2] == ("release", "delete-asset")) == 2
    saved = json.loads(next((root / "policy" / "outbox").glob("*.json")).read_text(encoding="utf-8"))
    assert saved["status"] == "done" and saved["permalink"].endswith("/abc/")
    assert ob.publish("policy", now=late, pub=pub, run=run, root=root, workdir=tmp_path / "w", progress=lambda m: None) is None
    assert len([c for c in pub.calls if c[0] == "publish"]) == 1                      # 두 번 올리지 않는다


def test_already_posted_key_is_marked_done_without_publishing(tmp_path):
    root, run, pub = tmp_path / "data", FakeGh(release_exists=True), FakePub()
    item = ob.add("policy", folder(tmp_path), "2026-09-15T18:30", run=run, root=root, progress=lambda m: None)
    (root / "policy" / "posted.jsonl").write_text(json.dumps({"key": item["key"]}) + chr(10), encoding="utf-8")
    assert ob.publish("policy", now=datetime(2026, 9, 15, 19, 0, tzinfo=KST), pub=pub, run=run, root=root, progress=lambda m: None) is None
    assert pub.calls == [] and json.loads((root / "policy" / "outbox" / f"{item['id']}.json").read_text(encoding="utf-8"))["status"] == "done"


def test_caption_without_dm_keyword_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        ob.add("policy", folder(tmp_path, caption="키워드 없음"), "2026-09-15T18:30", run=FakeGh(), root=tmp_path / "data", progress=lambda m: None)


class FakeCardPub(FakePub):
    """카드뉴스용 가짜 게시기: 올린 장수만큼 URL 을 돌려주고 캐러셀로 올린다."""

    def upload_public(self, paths, prefix):
        self.calls.append(("upload", [p.name for p in paths]))
        return [f"https://r2.test/{p.name}" for p in paths]

    def publish_carousel(self, ig, urls, caption, progress=print):
        self.calls.append(("carousel", list(urls), caption))
        return {"media_id": "m9", "permalink": "https://www.instagram.com/p/xyz/"}


def card_folder(tmp_path):
    d = tmp_path / "cards"
    d.mkdir()
    for i in range(1, 4):
        (d / f"{i:02d}.jpg").write_bytes(b"c")
    meta = {"key": "parent-cards-test", "title": "t", "hook": "h", "caption": "카드 설명. 댓글에 '휴직' 남기시면 DM",
            "hashtags": ["#육아휴직"], "dm_keyword": "휴직", "dm_text": "신청 방법 안내 " * 10}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return d


def test_cards_folder_is_queued_and_published_as_carousel(tmp_path):
    """카드뉴스 폴더(01.jpg…)도 대기열에 넣고 캐러셀로 게시한다 (2026-09-16)."""
    root, run, pub = tmp_path / "data", FakeGh(release_exists=True), FakeCardPub()
    item = ob.add("parent", card_folder(tmp_path), "2026-09-16T18:30", run=run, root=root, progress=lambda m: None)
    assert len(item["cards"]) == 3 and "video" not in item
    row = ob.publish("parent", now=datetime(2026, 9, 16, 18, 31, tzinfo=KST), pub=pub, run=run, root=root,
                     workdir=tmp_path / "w", progress=lambda m: None)
    assert row is not None and row["kind"] == "carousel" and row["media_id"] == "m9"
    assert [c[0] for c in pub.calls].count("carousel") == 1 and len(pub.calls[0][1]) == 3
    assert sum(1 for c in run.calls if c[:2] == ("release", "delete-asset")) == 3
