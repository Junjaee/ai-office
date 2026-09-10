from pathlib import Path

from catalog import MinutesEntry
from store import DriveApiStore


class FakeDrive:
    """폴더/파일을 메모리에 두는 가짜 Drive 클라이언트."""

    def __init__(self):
        self.files = {}          # id -> {"name","parent","data","mime"}
        self.seq = 0
        self.calls = []

    def _new(self, parent, name, data=None, mime=None):
        self.seq += 1
        fid = f"id{self.seq}"
        self.files[fid] = {"name": name, "parent": parent, "data": data, "mime": mime}
        return fid

    def find(self, parent_id, name):
        for fid, f in self.files.items():
            if f["parent"] == parent_id and f["name"] == name:
                return {"id": fid, "name": name}
        return None

    def create_folder(self, parent_id, name):
        self.calls.append(("folder", parent_id, name))
        return self._new(parent_id, name, mime="folder")

    def upload(self, parent_id, name, data, mime, file_id=None):
        self.calls.append(("upload", name, len(data), file_id))
        if file_id:
            self.files[file_id]["data"] = data
            return file_id
        return self._new(parent_id, name, data, mime)

    def download(self, file_id):
        return self.files[file_id]["data"]

    def free_gb(self):
        return 42.0


def entry(**kw):
    base = dict(id=57155, th=22, cls=2, committee="재정경제기획위원회", sess="438",
                title="재정경제기획위원회 제1차", temp=True, has_pdf=True)
    base.update(kw)
    return MinutesEntry(**base)


def test_starts_with_empty_manifest_when_drive_has_none():
    drive = FakeDrive()
    store = DriveApiStore(drive, "root")
    assert store.manifest == {}
    assert store.free_gb() == 42.0


def test_save_pdf_creates_nested_folders_once_and_overwrites_same_name():
    drive = FakeDrive()
    store = DriveApiStore(drive, "root")
    rel = Path("제22대/상임위원회/재정경제기획위원회/a.pdf")
    assert store.save_pdf(rel, b"%PDF-1") == 6
    folders = [c for c in drive.calls if c[0] == "folder"]
    assert [c[2] for c in folders] == ["제22대", "상임위원회", "재정경제기획위원회"]
    # 같은 폴더에 두 번째 파일: 폴더는 다시 만들지 않는다
    store.save_pdf(Path("제22대/상임위원회/재정경제기획위원회/b.pdf"), b"%PDF-2")
    assert len([c for c in drive.calls if c[0] == "folder"]) == 3
    # 같은 이름은 덮어쓰기(update)
    store.save_pdf(rel, b"%PDF-1-final")
    last = drive.calls[-1]
    assert last[0] == "upload" and last[3] is not None
    fid = drive.find(store._folder("제22대/상임위원회/재정경제기획위원회"), "a.pdf")["id"]
    assert drive.download(fid) == b"%PDF-1-final"


def test_manifest_and_log_roundtrip_through_drive():
    drive = FakeDrive()
    store = DriveApiStore(drive, "root")
    store.record(entry(), status="ok", path="p", size=1)
    store.save_manifest()
    store.log_run("daily", ["신규 1건"])
    store.log_run("daily", ["신규 0건"])
    again = DriveApiStore(drive, "root")
    assert again.manifest["57155"]["status"] == "ok"
    log = again._read_text("_수집로그.md")
    assert log.count("## ") == 2 and "신규 1건" in log
    # manifest 파일은 하나만 존재(덮어쓰기)
    assert sum(1 for f in drive.files.values() if f["name"] == "_manifest.json") == 1


def test_reuses_existing_folders_on_drive():
    drive = FakeDrive()
    root_child = drive._new("root", "제22대", mime="folder")
    store = DriveApiStore(drive, "root")
    store.save_pdf(Path("제22대/국회본회의/x.pdf"), b"%PDF")
    assert ("folder", "root", "제22대") not in drive.calls
    assert drive.files[drive.find(root_child, "국회본회의")["id"]]["parent"] == root_child
