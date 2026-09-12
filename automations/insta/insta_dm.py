"""댓글 → DM 자동 답장 (표준 라이브러리만 — 매시 예약 확인 실행에서 의존성 설치 전에 돈다).

사용자 결정 2026-09-12: 게시물마다 "댓글에 '<키워드>' 남기면 프롬프트를 DM 으로" 유도하고, 댓글이 달리면 그 글의 프롬프트(dm_text)를
비공개 답장(private reply)으로 보낸다. 다른 AI 계정들이 ManyChat 으로 하는 것을 우리 API 로 직접 한다.

- 대상: data/insta/<계정>/posted.jsonl 의 최근 7일 게시물 중 dm_text 가 있는 것 (비공개 답장은 댓글 뒤 7일 안, 댓글당 1번만 가능)
- 판정: 댓글에 dm_keyword 가 들어 있으면(키워드가 없으면 아무 댓글이나), 우리 계정 댓글은 제외
- 답장: 비공개 답장(DM) + 공개 답글("DM 보냈어요") — 댓글 수가 늘어 알고리즘에도 유리
- 기록: data/insta/<계정>/dm_log.jsonl (comment_id 별 1회, 실패도 기록해 재시도 폭주 방지)
- 권한: 토큰에 instagram_business_manage_messages, instagram_business_manage_comments 가 있어야 한다. 없으면 한 줄 안내하고 끝.

사용: python insta_dm.py --account aitips   (환경변수 INSTA_<계정>_TOKEN / INSTA_<계정>_USER_ID)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

GRAPH = "https://graph.instagram.com/v23.0"
HERE = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
WINDOW_DAYS = 7
MAX_PER_RUN = 60
PUBLIC_REPLY = "DM 으로 보내드렸어요 📩 확인해 보세요!"
PERMISSION_HINT = ("토큰에 메시지·댓글 권한이 없어요 — Meta 앱 'API 설정(Instagram 로그인)'에서 instagram_business_manage_messages, "
                   "instagram_business_manage_comments 를 켜고 토큰을 다시 만들어 GitHub Secrets INSTA_<계정>_TOKEN 에 넣어 주세요")


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str, code: int | None = None):
        super().__init__(f"Instagram 오류 {status}: {message} (code {code})")
        self.status, self.message, self.code = status, message, code

    @property
    def permission(self) -> bool:
        return self.code in (10, 200, 190, 3) or "permission" in self.message.lower() or "OAuth" in self.message


def api(method: str, path: str, token: str, params: dict | None = None, body: dict | None = None, timeout: int = 30) -> dict:
    """Graph API 한 번 호출. GET 은 쿼리, POST 는 JSON 본문."""
    params = {**(params or {}), "access_token": token}
    url = f"{GRAPH}/{path}?{urllib.parse.urlencode(params)}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": "ai-office-insta/1.0", **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8")).get("error", {})
        except Exception:  # noqa: BLE001
            err = {}
        raise ApiError(e.code, err.get("message", str(e)), err.get("code")) from None


def fetch_comments(media_id: str, token: str, *, pages: int = 3, call=api) -> list[dict]:
    """게시물의 댓글 [{id, text, username, timestamp}] (최근 것부터, 최대 pages 쪽)."""
    out: list[dict] = []
    path, params = f"{media_id}/comments", {"fields": "id,text,username,timestamp", "limit": 50}
    for _ in range(pages):
        data = call("GET", path, token, params)
        out.extend(data.get("data", []))
        nxt = (data.get("paging") or {}).get("cursors", {}).get("after")
        if not nxt or not data.get("data"):
            break
        params = {**params, "after": nxt}
    return out


def send_private_reply(user_id: str, comment_id: str, text: str, token: str, call=api) -> dict:
    return call("POST", f"{user_id}/messages", token, body={"recipient": {"comment_id": comment_id}, "message": {"text": text[:1000]}})


def reply_public(comment_id: str, text: str, token: str, call=api) -> dict:
    return call("POST", f"{comment_id}/replies", token, params={"message": text})


def matches(text: str, keyword: str) -> bool:
    """키워드가 있으면 댓글에 그 말이 들어 있어야 하고(대소문자·공백 무시), 없으면 아무 댓글이나."""
    if not keyword:
        return bool((text or "").strip())
    norm = lambda s: "".join(str(s).lower().split())  # noqa: E731
    return norm(keyword) in norm(text)


def _parse(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(s).replace("+0000", "+00:00"))
    except ValueError:
        return None


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def run(*, posted: list[dict], log: list[dict], token: str, user_id: str, own_username: str, now: datetime,
        call=api, public_reply: str = PUBLIC_REPLY, max_per_run: int = MAX_PER_RUN, progress=print) -> tuple[list[dict], dict]:
    """최근 7일 게시물의 댓글을 보고 답장. 반환: (새 로그 항목들, 요약 {checked, sent, skipped, failed, permission})."""
    done = {r["comment_id"] for r in log}
    new: list[dict] = []
    summary = {"checked": 0, "sent": 0, "failed": 0, "permission": False, "posts": 0}
    cutoff = now - timedelta(days=WINDOW_DAYS)
    for row in posted:
        text = str(row.get("dm_text") or "").strip()
        when = _parse(row.get("posted_at") or f"{row.get('date')}T00:00:00+09:00")
        if not text or not row.get("media_id") or (when and when < cutoff):
            continue
        summary["posts"] += 1
        try:
            comments = fetch_comments(row["media_id"], token, call=call)
        except ApiError as exc:
            summary["failed"] += 1
            if exc.permission:
                summary["permission"] = True
                progress(PERMISSION_HINT)
                return new, summary
            progress(f"댓글 조회 실패 — {row.get('hook', '')[:30]}: {exc}")
            continue
        keyword = str(row.get("dm_keyword") or "").strip()
        for c in comments:
            cid = str(c.get("id"))
            if cid in done or (own_username and str(c.get("username", "")).lower() == own_username.lower()):
                continue
            summary["checked"] += 1
            if not matches(c.get("text", ""), keyword):
                continue
            if summary["sent"] + summary["failed"] >= max_per_run:
                progress("이번 실행 상한 도달 — 나머지는 다음 시간에")
                return new, summary
            entry = {"comment_id": cid, "media_id": row["media_id"], "username": c.get("username", ""), "comment": str(c.get("text", ""))[:80],
                     "at": now.isoformat(timespec="seconds")}
            try:
                send_private_reply(user_id, cid, text, token, call=call)
                entry["status"] = "sent"
                summary["sent"] += 1
                try:
                    reply_public(cid, public_reply, token, call=call)
                except ApiError as exc:   # 공개 답글 실패는 치명적이지 않음
                    entry["public_reply_error"] = str(exc)[:100]
                progress(f"DM 보냄 → @{c.get('username', '')} ({row.get('hook', '')[:24]})")
            except ApiError as exc:
                entry["status"], entry["error"] = "failed", str(exc)[:160]
                summary["failed"] += 1
                if exc.permission:
                    summary["permission"] = True
                    progress(PERMISSION_HINT)
                    new.append(entry)
                    return new, summary
                progress(f"DM 실패 → @{c.get('username', '')}: {exc}")
            new.append(entry)
            done.add(cid)
    return new, summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default=os.environ.get("INSTA_ACCOUNT", "aitips"))
    ap.add_argument("--dry-run", action="store_true", help="댓글만 읽고 보내지 않는다")
    args = ap.parse_args()
    up = args.account.upper()
    token, user_id = os.environ.get(f"INSTA_{up}_TOKEN", "").strip(), os.environ.get(f"INSTA_{up}_USER_ID", "").strip()
    if not token:
        print(f"INSTA_{up}_TOKEN 이 없어 댓글 답장을 건너뜁니다")
        return 0
    data_dir = HERE.parent.parent / "data" / "insta" / args.account
    posted = load_jsonl(data_dir / "posted.jsonl")
    log_path = data_dir / "dm_log.jsonl"
    log = load_jsonl(log_path)
    try:
        me = api("GET", "me", token, {"fields": "user_id,username"})
    except ApiError as exc:
        print(f"계정 확인 실패: {exc}")
        return 0
    user_id = user_id or str(me.get("user_id", ""))
    call = (lambda m, p, t, params=None, body=None: api(m, p, t, params) if m == "GET" else {"dry": True}) if args.dry_run else api
    new, summary = run(posted=posted, log=log, token=token, user_id=user_id, own_username=str(me.get("username", "")),
                       now=datetime.now(timezone.utc), call=call)
    if new and not args.dry_run:
        data_dir.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            for e in new:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    print(f"댓글 답장: 게시물 {summary['posts']}건 · 확인 {summary['checked']} · DM {summary['sent']} · 실패 {summary['failed']}"
          + (" · 권한 없음" if summary["permission"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
