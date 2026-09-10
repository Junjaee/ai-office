"""Google Drive API 얇은 래퍼.

GitHub Actions처럼 드라이브 동기화 폴더가 없는 환경에서 파일을 올리고 내려받는다.
인증은 사용자 OAuth(리프레시 토큰)로, 파일 소유자는 사용자 본인이 된다.

환경변수: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN
"""
from __future__ import annotations

import io
import os
from typing import Protocol

FOLDER = "application/vnd.google-apps.folder"


class DriveClientLike(Protocol):
    def find(self, parent_id: str, name: str) -> dict | None: ...
    def create_folder(self, parent_id: str, name: str) -> str: ...
    def upload(self, parent_id: str, name: str, data: bytes, mime: str, file_id: str | None = None) -> str: ...
    def download(self, file_id: str) -> bytes: ...
    def free_gb(self) -> float: ...


def credentials_from_env():
    from google.oauth2.credentials import Credentials

    missing = [k for k in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Google 인증 환경변수가 없습니다: {', '.join(missing)}")
    return Credentials(
        token=None,
        refresh_token=os.environ["GOOGLE_REFRESH_TOKEN"],
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/drive"],
    )


def _escape(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


class DriveClient:
    """googleapiclient 위의 최소 기능. 이름은 폴더 안에서 유일하다고 가정한다."""

    def __init__(self, service=None):
        if service is None:
            from googleapiclient.discovery import build

            service = build("drive", "v3", credentials=credentials_from_env(), cache_discovery=False)
        self.svc = service

    def find(self, parent_id: str, name: str) -> dict | None:
        q = f"'{parent_id}' in parents and name = '{_escape(name)}' and trashed = false"
        res = self.svc.files().list(q=q, fields="files(id,name,mimeType,size)", pageSize=2, spaces="drive").execute()
        files = res.get("files", [])
        return files[0] if files else None

    def create_folder(self, parent_id: str, name: str) -> str:
        meta = {"name": name, "mimeType": FOLDER, "parents": [parent_id]}
        return self.svc.files().create(body=meta, fields="id").execute()["id"]

    def upload(self, parent_id: str, name: str, data: bytes, mime: str, file_id: str | None = None) -> str:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=len(data) > 5 * 1024 * 1024)
        if file_id:
            return self.svc.files().update(fileId=file_id, media_body=media, fields="id").execute()["id"]
        meta = {"name": name, "parents": [parent_id]}
        return self.svc.files().create(body=meta, media_body=media, fields="id").execute()["id"]

    def download(self, file_id: str) -> bytes:
        return self.svc.files().get_media(fileId=file_id).execute()

    def free_gb(self) -> float:
        quota = self.svc.about().get(fields="storageQuota").execute().get("storageQuota", {})
        limit = int(quota.get("limit", 0) or 0)
        usage = int(quota.get("usage", 0) or 0)
        if not limit:
            return 999.0
        return (limit - usage) / 1024 ** 3
