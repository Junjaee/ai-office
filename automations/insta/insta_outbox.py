"""완성 릴스 대기열(outbox) — 이 PC 에서 만든 릴스를 GitHub 에 올려 두면, GitHub 게시 실행이 정해진 시각에 올린다 (2026-09-15 사용자 결정).

해설형 영상 릴스는 원본(레딧·유튜브)을 GitHub 서버에서 받을 수 없어 이 PC 에서 만든다. 게시는 GitHub 이 한다.
- 영상·표지: GitHub 릴리스 'outbox-<계정>' 의 첨부 파일. 게시 뒤 지운다(남의 영상이 공개 저장소 기록에 영구히 남지 않게).
- 게시 정보: data/insta/<계정>/outbox/<id>.json
  {id, due, status(queued|done|failed), tries, key, title, hook, caption, hashtags, dm_keyword, dm_text, credit, source_url, video, thumb}
- 이미 올린 key 면 게시하지 않고 done 처리(중복 게시 방지). 게시 직후 posted.jsonl 에 dm_keyword·dm_text 까지 기록 → 매시 댓글 DM.

사용:
  python insta_outbox.py add --account policy --dir <reel.mp4·thumb.jpg·meta.json 폴더> --due 2026-09-15T18:30   (이 PC, gh 로그인 필요)
  python insta_outbox.py publish --account policy                                                               (GitHub 게시 실행, 매시)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
KST = timezone(timedelta(hours=9))
NL = chr(10)
REQUIRED = ("key", "title", "hook", "caption", "dm_keyword", "dm_text")
MAX_TRIES = 3


def tag_of(account: str) -> str:
    return f"outbox-{account}"


def data_root(root: Path | None = None) -> Path:
    return root or REPO / "data" / "insta"


def outbox_dir(account: str, root: Path | None = None) -> Path:
    return data_root(root) / account / "outbox"


def posted_path(account: str, root: Path | None = None) -> Path:
    return data_root(root) / account / "posted.jsonl"


def gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=check)


def parse_due(s: str) -> datetime:
    d = datetime.fromisoformat(str(s))
    return d if d.tzinfo else d.replace(tzinfo=KST)


def check_meta(meta: dict) -> None:
    missing = [k for k in REQUIRED if not str(meta.get(k) or "").strip()]
    if missing:
        raise ValueError("게시 정보에 빠진 항목: " + ", ".join(missing))
    if str(meta["dm_keyword"]) not in str(meta["caption"]):
        raise ValueError("캡션에 댓글 키워드가 없습니다: " + str(meta["dm_keyword"]))
    if len(str(meta["dm_text"])) < 60:
        raise ValueError("DM 내용이 너무 짧습니다(60자 이상)")


def build_caption(meta: dict) -> str:
    tags = " ".join(meta.get("hashtags") or [])
    return str(meta["caption"]).rstrip() + ((NL + NL + tags) if tags else "")


def already_posted(path: Path, key: str) -> bool:
    if not path.exists():
        return False
    return any(json.loads(ln).get("key") == key for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip())


def save_item(account: str, item: dict, root: Path | None = None) -> Path:
    d = outbox_dir(account, root)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{item['id']}.json"
    p.write_text(json.dumps(item, ensure_ascii=False, indent=1) + NL, encoding="utf-8")
    return p


def load_items(account: str, root: Path | None = None) -> list[dict]:
    d = outbox_dir(account, root)
    items = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(d.glob("*.json"))] if d.exists() else []
    return sorted(items, key=lambda i: str(i.get("due", "")))


def due_items(items: list[dict], now: datetime) -> list[dict]:
    return [i for i in items if i.get("status") == "queued" and parse_due(i["due"]) <= now]


def add(account: str, folder: Path, due: str, *, run=gh, root: Path | None = None, now: datetime | None = None, progress=print) -> dict:
    """완성 릴스 폴더를 대기열에 넣는다: 영상·표지는 릴리스 첨부로 올리고 게시 정보 json 을 저장한다(커밋은 부르는 쪽이)."""
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    check_meta(meta)
    card_files = sorted(folder.glob("[0-9][0-9].jpg"))          # 카드뉴스 폴더면 01.jpg, 02.jpg …
    if not card_files:
        for name in ("reel.mp4", "thumb.jpg"):
            if not (folder / name).exists():
                raise FileNotFoundError(str(folder / name))
    when = parse_due(due)
    item_id = when.strftime("%Y%m%d-%H%M") + "-" + hashlib.sha1(str(meta["key"]).encode("utf-8")).hexdigest()[:6]
    video, thumb = f"reel-{item_id}.mp4", f"thumb-{item_id}.jpg"
    cards = [f"card-{item_id}-{i:02d}.jpg" for i in range(1, len(card_files) + 1)]
    tag = tag_of(account)
    if run("release", "view", tag, check=False).returncode != 0:
        run("release", "create", tag, "--prerelease", "--title", f"인스타 대기 게시물 ({account})",
            "--notes", "게시 전 완성 릴스·카드 보관함. 게시되면 첨부 파일을 지운다 (automations/insta/insta_outbox.py).")
    with tempfile.TemporaryDirectory() as tmp:
        if card_files:
            copies = []
            for src, name in zip(card_files, cards):
                dst = Path(tmp) / name
                shutil.copy(src, dst)
                copies.append(str(dst))
            run("release", "upload", tag, *copies, "--clobber")
        else:
            tv, tt = Path(tmp) / video, Path(tmp) / thumb
            shutil.copy(folder / "reel.mp4", tv)
            shutil.copy(folder / "thumb.jpg", tt)
            run("release", "upload", tag, str(tv), str(tt), "--clobber")
    item = {**meta, "id": item_id, "account": account, "due": when.isoformat(timespec="minutes"), "status": "queued", "tries": 0,
            "added_at": (now or datetime.now(KST)).isoformat(timespec="seconds")}
    item.update({"cards": cards} if card_files else {"video": video, "thumb": thumb})
    save_item(account, item, root)
    progress(f"대기열에 넣음 {item_id} · 게시 {item['due']}")
    return item


def _cleanup(account: str, item: dict, run) -> None:
    for asset in [item.get("video"), item.get("thumb"), *(item.get("cards") or [])]:
        if asset:
            run("release", "delete-asset", tag_of(account), asset, "--yes", check=False)


def publish(account: str, *, now: datetime | None = None, pub=None, run=gh, root: Path | None = None,
            workdir: Path | None = None, progress=print) -> dict | None:
    """게시 시각이 지난 대기 릴스 하나를 올린다. 올렸으면 게시 기록 한 줄, 아니면 None."""
    now = now or datetime.now(KST)
    items = due_items(load_items(account, root), now)
    if not items:
        progress("게시할 대기 릴스 없음")
        return None
    item = items[0]
    if already_posted(posted_path(account, root), item["key"]):
        item.update(status="done", note="이미 게시된 글")
        save_item(account, item, root)
        _cleanup(account, item, run)
        progress("이미 올린 글이라 건너뜀: " + item["key"])
        return None
    if pub is None:
        import insta_publisher as pub
    token, user_id = pub.account_env(account)
    if not token:
        progress(f"INSTA_{account.upper()}_TOKEN 이 없어 대기 릴스를 건너뜁니다")
        return None
    item["tries"] = int(item.get("tries", 0)) + 1
    if item["tries"] > MAX_TRIES:
        item.update(status="failed", note=f"{MAX_TRIES}번 실패")
        save_item(account, item, root)
        progress("대기 릴스 실패 처리: " + item["id"])
        return None
    save_item(account, item, root)
    work = workdir or Path(tempfile.mkdtemp())
    assets = list(item.get("cards") or [item["video"], item["thumb"]])
    picks = [x for a in assets for x in ("-p", a)]
    run("release", "download", tag_of(account), *picks, "-D", str(work), "--clobber")
    ig = pub.Instagram(token, user_id)
    urls = pub.upload_public([work / a for a in assets], f"insta/{account}/{now.strftime('%Y-%m-%d-%H%M%S')}-outbox")
    if item.get("cards"):
        progress(f"카드 {len(urls)}장 공개 URL 준비")
        res = pub.publish_carousel(ig, urls, build_caption(item), progress=progress)
    else:
        progress("영상 공개 URL 준비")
        res = pub.publish_reel(ig, urls[0], build_caption(item), cover_url=urls[1], progress=progress)
    row = {"date": now.strftime("%Y-%m-%d"), "account": account, "key": item["key"], "title": item["title"], "hook": item["hook"],
           "media_id": res["media_id"], "permalink": res.get("permalink") or "https://www.instagram.com/", "video_url": urls[0],
           "posted_at": now.isoformat(timespec="seconds"), "dm_keyword": item["dm_keyword"], "dm_text": item["dm_text"],
           "kind": "carousel" if item.get("cards") else "reel_commentary",
           "credit": item.get("credit", ""), "source_url": item.get("source_url", ""), "provider": "outbox"}
    pp = posted_path(account, root)
    pp.parent.mkdir(parents=True, exist_ok=True)
    with pp.open("a", encoding="utf-8") as f:                # 게시 직후 바로 기록 — 뒤에서 무슨 오류가 나도 다시 올리지 않게
        f.write(json.dumps(row, ensure_ascii=False) + NL)
    item.update(status="done", posted_at=row["posted_at"], permalink=row["permalink"], media_id=row["media_id"])
    save_item(account, item, root)
    _cleanup(account, item, run)
    progress("대기 릴스 게시 완료 " + str(row["permalink"]))
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="완성 릴스 대기열")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="이 PC 의 완성 릴스를 대기열에 넣는다")
    a.add_argument("--account", required=True)
    a.add_argument("--dir", required=True)
    a.add_argument("--due", required=True, help="게시 시각 KST, 예 2026-09-15T18:30")
    p = sub.add_parser("publish", help="게시 시각이 지난 대기 릴스 하나를 올린다")
    p.add_argument("--account", required=True)
    args = ap.parse_args()
    if args.cmd == "add":
        add(args.account, Path(args.dir), args.due)
    else:
        publish(args.account)
    return 0


if __name__ == "__main__":
    sys.exit(main())
