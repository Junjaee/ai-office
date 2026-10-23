"""회의록 글자 파일과 manifest 저장소.

- LocalStore: 폴더에 쓴다 (시험·로컬 실행)
- DriveStore: 구글 드라이브 API 로 올린다 (GitHub Actions). automations/common/google_drive.DriveClient 사용.

구조: <루트>/<의회 이름>/제N대/제K회/<위원회>_<차수>_<날짜>.txt, 의회마다 manifest.json 하나.
manifest: { doc_id: {"path", "date", "temp", "size", "title", "saved_at"} }
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lcouncil_sites import Doc

KST = timezone(timedelta(hours=9))
_FORBIDDEN = re.compile(r'[\\/:*?"<>|]')


def sanitize(name: str) -> str:
    return _FORBIDDEN.sub("_", name).strip() or "_"


def relative_path(doc: Doc) -> list[str]:
    """[제N대, 제K회, 파일명.txt]"""
    parts = [sanitize(doc.committee or "회의"), doc.order, doc.date]
    fname = "_".join(p for p in parts if p) + ".txt"
    return [f"제{doc.th}대", f"제{doc.session}회", fname]


class BaseStore:
    def __init__(self):
        self.manifest: dict[str, dict] = {}

    def needs_fetch(self, doc: Doc) -> str | None:
        """'new' | 'replaced' | None(건너뜀)"""
        prev = self.manifest.get(doc.id)
        if prev is None:
            return "new"
        if prev.get("temp") and not doc.temp:
            return "replaced"
        return None

    def record(self, doc: Doc, path: str, size: int) -> None:
        self.manifest[doc.id] = {"path": path, "date": doc.date, "temp": doc.temp, "size": size,
                                 "title": doc.title, "saved_at": datetime.now(KST).isoformat(timespec="seconds")}

    def total_ok(self) -> int:
        return len(self.manifest)


class LocalStore(BaseStore):
    def __init__(self, root: str | Path, council_name: str):
        super().__init__()
        self.dir = Path(root) / sanitize(council_name)
        self.dir.mkdir(parents=True, exist_ok=True)
        mf = self.dir / "manifest.json"
        if mf.exists():
            self.manifest = json.loads(mf.read_text(encoding="utf-8"))

    def save_text(self, doc: Doc, text: str) -> tuple[str, int]:
        parts = relative_path(doc)
        p = self.dir.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode("utf-8")
        p.write_bytes(data)
        return "/".join(parts), len(data)

    def save_manifest(self) -> None:
        (self.dir / "manifest.json").write_text(json.dumps(self.manifest, ensure_ascii=False, indent=1), encoding="utf-8")


class DriveStore(BaseStore):
    """폴더 id 를 한 번 찾으면 기억해 둬 요청 수를 줄인다."""

    def __init__(self, client, root_folder_id: str, council_name: str):
        super().__init__()
        self.c = client
        self.folders: dict[str, str] = {}
        self.council_dir = self._folder(root_folder_id, sanitize(council_name))
        found = client.find(self.council_dir, "manifest.json")
        self.manifest_id = found["id"] if found else None
        if self.manifest_id:
            self.manifest = json.loads(client.download(self.manifest_id).decode("utf-8"))

    def _folder(self, parent: str, name: str) -> str:
        key = f"{parent}/{name}"
        if key not in self.folders:
            found = self.c.find(parent, name)
            self.folders[key] = found["id"] if found else self.c.create_folder(parent, name)
        return self.folders[key]

    def save_text(self, doc: Doc, text: str) -> tuple[str, int]:
        parts = relative_path(doc)
        parent = self.council_dir
        for name in parts[:-1]:
            parent = self._folder(parent, name)
        data = text.encode("utf-8")
        prev = self.manifest.get(doc.id, {})
        file_id = prev.get("file_id")
        if prev and not file_id:   # 예전 기록에 file_id 가 없을 때만 찾는다(새 문서는 바로 올려 요청을 아낀다)
            found = self.c.find(parent, parts[-1])
            file_id = found["id"] if found else None
        new_id = self.c.upload(parent, parts[-1], data, "text/plain", file_id=file_id)
        self._pending_file_id = new_id
        return "/".join(parts), len(data)

    def record(self, doc: Doc, path: str, size: int) -> None:
        super().record(doc, path, size)
        fid = getattr(self, "_pending_file_id", None)
        if fid:
            self.manifest[doc.id]["file_id"] = fid

    def save_manifest(self) -> None:
        data = json.dumps(self.manifest, ensure_ascii=False, indent=1).encode("utf-8")
        self.manifest_id = self.c.upload(self.council_dir, "manifest.json", data, "application/json",
                                         file_id=self.manifest_id)
