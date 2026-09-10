"""기사 모니터링 결과 저장소(구글 드라이브). 글 파일만 쓰므로 텍스트 읽기·쓰기면 충분하다.

폴더 모양:
  12. 언론모니터링/
  ├── _manifest.json          이미 본 기사 (중복 방지)
  └── 2026/2026-09/2026-09-10.md
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path, PurePosixPath

MANIFEST = "_manifest.json"


def day_path(day: str) -> PurePosixPath:
    """'2026-09-10' → 2026/2026-09/2026-09-10.md"""
    year, month, _ = day.split("-")
    return PurePosixPath(year) / f"{year}-{month}" / f"{day}.md"


class BaseStore:
    def read_text(self, rel: PurePosixPath | str) -> str | None:
        raise NotImplementedError

    def write_text(self, rel: PurePosixPath | str, text: str) -> None:
        raise NotImplementedError

    def load_manifest(self) -> dict:
        text = self.read_text(MANIFEST)
        return json.loads(text) if text else {}

    def save_manifest(self, manifest: dict) -> None:
        self.write_text(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=1))


class LocalStore(BaseStore):
    """이 PC 의 드라이브 동기화 폴더에 쓴다 (로컬 확인용)."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def read_text(self, rel):
        p = self.root / str(rel)
        return p.read_text(encoding="utf-8") if p.exists() else None

    def write_text(self, rel, text):
        p = self.root / str(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)


class DriveStore(BaseStore):
    """Google Drive API 저장소. client 는 common/google_drive.py 의 DriveClient(또는 같은 모양의 가짜)."""

    def __init__(self, client, parent_id: str, folder_name: str):
        self.client = client
        found = client.find(parent_id, folder_name)
        self.root_id = found["id"] if found else client.create_folder(parent_id, folder_name)
        self._folder_ids: dict[str, str] = {"": self.root_id}

    def folder_link(self) -> str:
        return f"https://drive.google.com/drive/folders/{self.root_id}"

    def _folder(self, rel_dir: PurePosixPath | str) -> str:
        key = str(rel_dir).strip("/")
        if key in (".", ""):
            key = ""
        if key in self._folder_ids:
            return self._folder_ids[key]
        parent_key, _, name = key.rpartition("/")
        parent_id = self._folder(parent_key)
        found = self.client.find(parent_id, name)
        fid = found["id"] if found else self.client.create_folder(parent_id, name)
        self._folder_ids[key] = fid
        return fid

    def read_text(self, rel):
        posix = PurePosixPath(str(rel))
        f = self.client.find(self._folder(posix.parent), posix.name)
        return self.client.download(f["id"]).decode("utf-8") if f else None

    def write_text(self, rel, text):
        posix = PurePosixPath(str(rel))
        folder_id = self._folder(posix.parent)
        existing = self.client.find(folder_id, posix.name)
        mime = "application/json" if posix.name.endswith(".json") else "text/markdown"
        self.client.upload(folder_id, posix.name, text.encode("utf-8"), mime,
                           file_id=existing["id"] if existing else None)
