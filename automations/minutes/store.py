"""회의록 PDF·manifest·로그 저장소.

- LocalDriveStore: 이 PC의 드라이브 동기화 폴더에 쓴다 (로컬 실행용)
- DriveApiStore:   Google Drive API로 올린다 (GitHub Actions 등 서버 실행용)
두 저장소는 같은 인터페이스를 가지며 manifest 규칙은 BaseStore가 공유한다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path, PurePosixPath

from catalog import MinutesEntry

KST = timezone(timedelta(hours=9))
_FORBIDDEN = re.compile(r'[\\/:*?"<>|]')


def sanitize(name: str) -> str:
    return _FORBIDDEN.sub("_", name).strip()


def relative_path(e: MinutesEntry, filename: str | None) -> Path:
    """저장 루트 아래 상대 경로: 제NN대/회의구분/위원회(/연도)/파일명.pdf"""
    name = sanitize(filename) if filename else f"제{e.th}대_{e.class_name}_{sanitize(e.committee)}_{e.id}.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    parts = [f"제{e.th}대"]
    if e.cls in (1, 4):
        parts.append(e.class_name)
    elif e.cls == 5:
        parts += [e.class_name, sanitize(e.committee), e.sess]
    else:
        parts += [e.class_name, sanitize(e.committee)]
    return Path(*parts) / name


class BaseStore:
    MANIFEST = "_manifest.json"
    LOG = "_수집로그.md"

    def __init__(self):
        self.manifest: dict[str, dict] = self._load_manifest()

    # --- 하위 클래스가 구현 ---
    def _read_text(self, name: str) -> str | None:
        raise NotImplementedError

    def _write_text(self, name: str, text: str) -> None:
        raise NotImplementedError

    def save_pdf(self, rel: Path, data: bytes) -> int:
        raise NotImplementedError

    def free_gb(self) -> float:
        raise NotImplementedError

    # --- 공통 ---
    def relative_path(self, e: MinutesEntry, filename: str | None) -> Path:
        return relative_path(e, filename)

    def _load_manifest(self) -> dict[str, dict]:
        text = self._read_text(self.MANIFEST)
        return json.loads(text) if text else {}

    def save_manifest(self) -> None:
        self._write_text(self.MANIFEST, json.dumps(self.manifest, ensure_ascii=False, indent=1))

    def record(self, e: MinutesEntry, *, status: str, path: str | None, size: int) -> None:
        prev = self.manifest.get(str(e.id))
        temp = e.temp
        if temp is None:
            # 임시 여부를 모르는 출처(Open API)는 이전 값을 유지하고, 처음이면 임시로 보고 나중에 재확인한다
            temp = prev["temp"] if prev else True
        self.manifest[str(e.id)] = {
            "th": e.th, "cls": e.cls, "committee": e.committee, "sess": e.sess,
            "title": e.title, "temp": temp, "has_pdf": e.has_pdf, "status": status,
            "path": path, "size": size,
            "downloaded_at": datetime.now(KST).isoformat(timespec="seconds"),
        }

    def needs_download(self, e: MinutesEntry) -> bool:
        prev = self.manifest.get(str(e.id))
        if prev is None:
            return e.has_pdf
        if prev["status"] == "ok":
            return bool(prev["temp"]) and e.temp is False   # 임시 → 확정 교체 (확정이 확인된 경우만)
        if prev["status"] == "no_pdf":
            return e.has_pdf
        return e.has_pdf                                 # error → 재시도

    def pending_temp(self, th: int, classes: tuple[int, ...] = (1, 2, 3, 4)) -> list[dict]:
        """확정본 교체를 기다리는(임시) 항목."""
        return [v for v in self.manifest.values()
                if v["th"] == th and v["cls"] in classes and v["status"] == "ok" and v.get("temp")]

    def log_run(self, mode: str, lines: list[str]) -> None:
        stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
        body = f"\n## {stamp} ({mode})\n" + "".join(f"- {ln}\n" for ln in lines)
        self._write_text(self.LOG, (self._read_text(self.LOG) or "") + body)


class LocalDriveStore(BaseStore):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        super().__init__()

    def _read_text(self, name: str) -> str | None:
        p = self.root / name
        return p.read_text(encoding="utf-8") if p.exists() else None

    def _write_text(self, name: str, text: str) -> None:
        p = self.root / name
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, p)

    def save_pdf(self, rel: Path, data: bytes) -> int:
        target = self.root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".pdf.part")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return len(data)

    def free_gb(self) -> float:
        return shutil.disk_usage(self.root).free / 1024 ** 3


class DriveApiStore(BaseStore):
    """Google Drive API 저장소. client는 google_drive.DriveClient(또는 같은 모양의 가짜)."""

    def __init__(self, client, root_folder_id: str):
        self.client = client
        self.root_id = root_folder_id
        self._folder_ids: dict[str, str] = {"": root_folder_id}
        super().__init__()

    def _folder(self, rel_dir: PurePosixPath | str) -> str:
        """상대 폴더 경로의 Drive 폴더 id. 없으면 만든다."""
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

    def _read_text(self, name: str) -> str | None:
        f = self.client.find(self.root_id, name)
        return self.client.download(f["id"]).decode("utf-8") if f else None

    def _write_text(self, name: str, text: str) -> None:
        f = self.client.find(self.root_id, name)
        mime = "application/json" if name.endswith(".json") else "text/markdown"
        self.client.upload(self.root_id, name, text.encode("utf-8"), mime, file_id=f["id"] if f else None)

    def save_pdf(self, rel: Path, data: bytes) -> int:
        posix = PurePosixPath(rel.as_posix())
        folder_id = self._folder(posix.parent)
        existing = self.client.find(folder_id, posix.name)
        self.client.upload(folder_id, posix.name, data, "application/pdf", file_id=existing["id"] if existing else None)
        return len(data)

    def free_gb(self) -> float:
        return self.client.free_gb()
