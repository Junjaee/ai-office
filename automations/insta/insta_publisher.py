"""업로드 — 카드 JPEG 를 공개 URL(Cloudflare R2)에 올리고 Instagram API 로 캐러셀을 게시한다.

환경변수:
  R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET, R2_PUBLIC_BASE (예 https://pub-xxxx.r2.dev)
  INSTA_<계정>_TOKEN (장기 토큰), INSTA_<계정>_USER_ID (없으면 /me 로 조회)
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

GRAPH = "https://graph.instagram.com/v23.0"


class MissingInstaToken(Exception):
    """INSTA_<계정>_TOKEN 이 비어 있다."""


class MissingR2Config(Exception):
    """R2_* 환경변수가 비어 있다."""


# ── R2 ──

def r2_client():
    import boto3

    acct = os.environ.get("R2_ACCOUNT_ID", "").strip()
    key = os.environ.get("R2_ACCESS_KEY_ID", "").strip()
    secret = os.environ.get("R2_SECRET_ACCESS_KEY", "").strip()
    if not (acct and key and secret and os.environ.get("R2_BUCKET") and os.environ.get("R2_PUBLIC_BASE")):
        raise MissingR2Config("R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY / R2_BUCKET / R2_PUBLIC_BASE 가 필요합니다")
    return boto3.client("s3", endpoint_url=f"https://{acct}.r2.cloudflarestorage.com",
                        aws_access_key_id=key, aws_secret_access_key=secret, region_name="auto")


def upload_public(paths: list[Path], prefix: str, *, client=None) -> list[str]:
    """파일들을 prefix/ 아래에 올리고 공개 URL 목록을 돌려준다."""
    client = client or r2_client()
    bucket = os.environ["R2_BUCKET"]
    base = os.environ["R2_PUBLIC_BASE"].rstrip("/")
    urls = []
    for p in paths:
        key = f"{prefix}/{p.name}"
        ctype = "video/mp4" if p.suffix.lower() == ".mp4" else ("image/png" if p.suffix.lower() == ".png" else "image/jpeg")
        client.upload_file(str(p), bucket, key, ExtraArgs={"ContentType": ctype})
        urls.append(f"{base}/{key}")
    return urls


# ── Instagram ──

class Instagram:
    def __init__(self, token: str, user_id: str = "", session: requests.Session | None = None, timeout: int = 60):
        if not (token or "").strip():
            raise MissingInstaToken("인스타그램 토큰이 비어 있습니다")
        self.token = token.strip()
        self.s = session or requests.Session()
        self.timeout = timeout
        self.user_id = user_id.strip() or self.me()["user_id"]

    def _req(self, method: str, path: str, **params) -> dict:
        params["access_token"] = self.token
        r = self.s.request(method, f"{GRAPH}/{path}", params=params if method == "GET" else None,
                           data=params if method != "GET" else None, timeout=self.timeout)
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"Instagram HTTP {r.status_code}: {r.text[:200]}")
        if not r.ok or "error" in data:
            err = data.get("error", {})
            raise RuntimeError(f"Instagram 오류 {r.status_code}: {err.get('message', r.text[:200])} (code {err.get('code')})")
        return data

    def me(self) -> dict:
        return self._req("GET", "me", fields="user_id,username")

    def create_item(self, image_url: str) -> str:
        return self._req("POST", f"{self.user_id}/media", image_url=image_url, is_carousel_item="true")["id"]

    def create_carousel(self, children: list[str], caption: str) -> str:
        params = {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption}
        return self._req("POST", f"{self.user_id}/media", **params)["id"]

    def create_single(self, image_url: str, caption: str, alt_text: str = "") -> str:
        params = {"image_url": image_url, "caption": caption}
        if alt_text:
            params["alt_text"] = alt_text
        return self._req("POST", f"{self.user_id}/media", **params)["id"]

    def create_reel(self, video_url: str, caption: str, cover_url: str = "", share_to_feed: bool = True) -> str:
        params = {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true" if share_to_feed else "false"}
        if cover_url:
            params["cover_url"] = cover_url
        return self._req("POST", f"{self.user_id}/media", **params)["id"]

    def wait_ready(self, container_id: str, *, tries: int = 20, delay: float = 3.0) -> None:
        for _ in range(tries):
            st = self._req("GET", container_id, fields="status_code,status")
            code = st.get("status_code")
            if code == "FINISHED":
                return
            if code == "ERROR":
                raise RuntimeError(f"컨테이너 처리 실패: {st.get('status')}")
            time.sleep(delay)
        raise RuntimeError("컨테이너 준비 대기 시간 초과")

    def publish(self, container_id: str) -> str:
        return self._req("POST", f"{self.user_id}/media_publish", creation_id=container_id)["id"]

    def permalink(self, media_id: str) -> str:
        return self._req("GET", media_id, fields="permalink").get("permalink", "")

    def metrics(self, media_id: str) -> dict:
        """게시물 지표: 좋아요·댓글 + 인사이트(views 조회, reach 도달, saved 저장, shares 공유, total_interactions)."""
        base = self._req("GET", media_id, fields="like_count,comments_count,permalink,timestamp,media_type")
        for metric in ("views,reach,saved,shares,total_interactions", "reach,saved,shares"):   # 옛 게시물·타입에 따라 일부 지표가 거부되면 줄여서 재시도
            try:
                ins = self._req("GET", f"{media_id}/insights", metric=metric)
                for row in ins.get("data", []):
                    base[row["name"]] = (row.get("values") or [{}])[0].get("value")
                break
            except RuntimeError as exc:
                base["insights_error"] = str(exc)[:120]
        return base

    def account(self) -> dict:
        """계정 요약: 팔로워·팔로잉·게시물 수."""
        return self._req("GET", "me", fields="user_id,username,followers_count,follows_count,media_count")


def publish_carousel(ig: Instagram, image_urls: list[str], caption: str, alt_text: str = "", progress=print) -> dict:
    """이미지 URL 들 → 캐러셀 게시. (media_id, permalink) 반환."""
    if len(image_urls) == 1:
        container = ig.create_single(image_urls[0], caption, alt_text)
    else:
        children = []
        for i, url in enumerate(image_urls, 1):
            children.append(ig.create_item(url))
            progress(f"컨테이너 {i}/{len(image_urls)}")
        container = ig.create_carousel(children, caption)
    ig.wait_ready(container)
    media_id = ig.publish(container)
    return {"media_id": media_id, "permalink": ig.permalink(media_id)}


def publish_reel(ig: Instagram, video_url: str, caption: str, cover_url: str = "", progress=print) -> dict:
    """영상 공개 URL → 릴스 게시(피드에도 표시). 영상 처리에 1~3분 걸리므로 오래 기다린다. (media_id, permalink) 반환."""
    container = ig.create_reel(video_url, caption, cover_url)
    progress("릴스 컨테이너 처리 중 (영상 변환)")
    ig.wait_ready(container, tries=60, delay=5.0)
    media_id = ig.publish(container)
    return {"media_id": media_id, "permalink": ig.permalink(media_id)}


def account_env(account: str) -> tuple[str, str]:
    up = account.upper()
    return os.environ.get(f"INSTA_{up}_TOKEN", ""), os.environ.get(f"INSTA_{up}_USER_ID", "")
