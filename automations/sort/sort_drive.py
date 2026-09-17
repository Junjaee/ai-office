"""수신함 정리 — 드라이브 폴더를 훑고, 파일 내용을 읽고, 옮긴다.

- folder_tree() · inbox_files(): 어디에 무엇이 있는지
- read_text(): 한글(.hwp/.hwpx)·PDF·텍스트에서 앞부분 글자 뽑기 (분류 판단용)
- move_file() · ensure_folder(): 실제 이동 (삭제는 하지 않는다)
- append_log(): 무엇을 어디로 옮겼는지 드라이브에 기록 (되돌릴 때 쓴다)

파일 이름·본문은 의원실 내부 자료다 → 저장소에는 남기지 않고 드라이브 기록 파일에만 쓴다.
"""
from __future__ import annotations

import io
import re
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))
FOLDER_MIME = "application/vnd.google-apps.folder"
LOG_NAME = "_정리기록.md"
TEXT_CHARS = 1200        # 분류에 쓸 본문 앞부분 길이
CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f-]")


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    size: int


@dataclass(frozen=True)
class Folder:
    id: str
    name: str
    count: int           # 안에 든 것 수 (폴더가 얼마나 쓰이는지 가늠)


def list_folders(service, parent_id: str) -> list[Folder]:
    """parent 바로 아래 폴더들(이름 순). 수신함 자신은 뺀다."""
    res = service.files().list(
        q=f"'{parent_id}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false",
        fields="files(id,name)", pageSize=100, orderBy="name").execute()
    out = []
    for f in res.get("files", []):
        kids = service.files().list(q=f"'{f['id']}' in parents and trashed = false",
                                    fields="files(id)", pageSize=1000).execute().get("files", [])
        out.append(Folder(f["id"], f["name"], len(kids)))
    return out


def inbox_files(service, inbox_id: str, skip: tuple[str, ...] = ()) -> list[Item]:
    """수신함에 있는 파일들(폴더 제외, 오래된 것부터)."""
    res = service.files().list(
        q=f"'{inbox_id}' in parents and trashed = false and mimeType != '{FOLDER_MIME}'",
        fields="files(id,name,size)", pageSize=100, orderBy="createdTime").execute()
    return [Item(f["id"], f["name"], int(f.get("size") or 0))
            for f in res.get("files", []) if f["name"] not in skip]


# ── 파일에서 글자 뽑기 ──────────────────────────────────────────────────────

def _hwpx_text(data: bytes) -> str:
    import zipfile

    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in sorted(n for n in z.namelist() if n.startswith("Contents/section")):
            out.append(re.sub(r"<[^>]+>", " ", z.read(name).decode("utf-8", "ignore")))
            if sum(len(x) for x in out) > TEXT_CHARS * 3:
                break
    return " ".join(out)


def _hwp_text(data: bytes) -> str:
    """한글 5.0(OLE 복합문서). BodyText 스트림을 풀어 글자 레코드(PARA_TEXT)만 모은다."""
    import olefile

    ole = olefile.OleFileIO(io.BytesIO(data))
    compressed = True
    if ole.exists("FileHeader"):
        compressed = bool(ole.openstream("FileHeader").read()[36] & 1)
    out: list[str] = []
    for entry in sorted(e for e in ole.listdir() if e and e[0] == "BodyText"):
        body = ole.openstream(entry).read()
        if compressed:
            body = zlib.decompress(body, -15)
        i = 0
        while i < len(body) - 4:
            header = int.from_bytes(body[i:i + 4], "little")
            tag, size = header & 0x3FF, (header >> 20) & 0xFFF
            i += 4
            if size == 0xFFF:
                size = int.from_bytes(body[i:i + 4], "little")
                i += 4
            if tag == 67:  # PARA_TEXT
                out.append(body[i:i + size].decode("utf-16le", "ignore"))
            i += size
        if sum(len(x) for x in out) > TEXT_CHARS * 3:
            break
    return " ".join(out)


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return " ".join((page.extract_text() or "") for page in reader.pages[:3])


def read_text(service, item: Item, max_chars: int = TEXT_CHARS) -> str:
    """파일 앞부분 글자. 읽을 수 없는 형식이거나 실패하면 빈 문자열(이름만으로 판단하게 둔다)."""
    ext = Path(item.name).suffix.lower()
    if ext not in (".hwp", ".hwpx", ".pdf", ".txt", ".md", ".csv"):
        return ""
    try:
        data = service.files().get_media(fileId=item.id).execute()
        if ext in (".txt", ".md", ".csv"):
            text = data.decode("utf-8", "ignore")
        elif ext == ".pdf":
            text = _pdf_text(data)
        elif ext == ".hwpx" or data[:2] == b"PK":      # 확장자가 .hwp 여도 내용이 hwpx 인 경우가 있다
            text = _hwpx_text(data)
        else:
            text = _hwp_text(data)
    except Exception:  # noqa: BLE001 - 분류는 이름만으로도 되므로 읽기 실패는 치명적이지 않다
        return ""
    return " ".join(CONTROL.sub(" ", text).split())[:max_chars]


# ── 옮기기 ────────────────────────────────────────────────────────────────

def ensure_folder(service, parent_id: str, name: str) -> str:
    """이름이 같은 폴더가 있으면 그 id, 없으면 만든다."""
    safe = name.replace("'", "\\'")
    got = service.files().list(
        q=f"'{parent_id}' in parents and name = '{safe}' and mimeType = '{FOLDER_MIME}' and trashed = false",
        fields="files(id)", pageSize=2).execute().get("files", [])
    if got:
        return got[0]["id"]
    return service.files().create(
        body={"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}, fields="id").execute()["id"]


def move_file(service, file_id: str, to_folder: str, from_folder: str) -> None:
    """파일을 옮긴다(복사·삭제가 아니라 부모만 바꾼다)."""
    service.files().update(fileId=file_id, addParents=to_folder, removeParents=from_folder,
                           fields="id").execute()


def append_log(service, folder_id: str, lines: list[str], now: datetime | None = None) -> None:
    """정리 기록을 드라이브의 _정리기록.md 에 덧붙인다(없으면 만든다). 되돌릴 때 이 기록을 본다."""
    from googleapiclient.http import MediaInMemoryUpload

    stamp = (now or datetime.now(KST)).strftime("%Y-%m-%d %H:%M")
    block = f"\n## {stamp}\n" + "\n".join(f"- {line}" for line in lines) + "\n"
    got = service.files().list(
        q=f"'{folder_id}' in parents and name = '{LOG_NAME}' and trashed = false",
        fields="files(id)", pageSize=2).execute().get("files", [])
    if got:
        old = service.files().get_media(fileId=got[0]["id"]).execute().decode("utf-8", "ignore")
        body = old + block
        service.files().update(fileId=got[0]["id"],
                               media_body=MediaInMemoryUpload(body.encode("utf-8"), mimetype="text/markdown")).execute()
        return
    body = f"# 수신함 정리 기록\n\n자동으로 옮긴 파일 목록입니다. 잘못 옮겼으면 이 기록을 보고 되돌리면 됩니다.\n{block}"
    service.files().create(body={"name": LOG_NAME, "parents": [folder_id]},
                           media_body=MediaInMemoryUpload(body.encode("utf-8"), mimetype="text/markdown"),
                           fields="id").execute()
