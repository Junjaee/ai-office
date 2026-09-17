"""수신함 정리 — do_work 흐름(계획 → 이동 → 기록). 가짜 드라이브·가짜 클로드, 네트워크 없음."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "common"))
import run_sort  # noqa: E402
from sort_drive import Folder, Item  # noqa: E402

CFG = {
    "committees": [{"label": "재경위", "inbox_id": "INBOX", "parent_id": "PARENT"}],
    "tasks": ["plan", "move"],
}


def work(dry_run=False):
    return argparse.Namespace(dry_run=dry_run, config="")


class FakeLLM:
    def __init__(self, moves):
        self.moves = moves
        self.asked = []

    def json(self, *, system, user, schema=None, retries=1):
        self.asked.append(user)
        return {"moves": self.moves}


def setup(monkeypatch, *, items, folders, moves):
    state = {"moved": [], "folders": list(folders), "log": [], "read": []}

    monkeypatch.setattr(run_sort, "drive_service", lambda: "SVC")
    monkeypatch.setattr(run_sort, "inbox_files", lambda svc, inbox, skip=(): list(items))
    monkeypatch.setattr(run_sort, "list_folders", lambda svc, parent: list(folders))
    monkeypatch.setattr(run_sort, "read_text",
                        lambda svc, item, **kw: state["read"].append(item.name) or f"{item.name} 본문")
    monkeypatch.setattr(run_sort, "ensure_folder",
                        lambda svc, parent, name: f"ID-{name}")
    monkeypatch.setattr(run_sort, "move_file",
                        lambda svc, fid, to, frm: state["moved"].append((fid, to, frm)))
    monkeypatch.setattr(run_sort, "append_log",
                        lambda svc, folder, lines, now=None: state["log"].append((folder, lines)))
    llm = FakeLLM(moves)
    monkeypatch.setattr(run_sort, "LLM", lambda providers: llm)
    state["llm"] = llm
    return state


ITEMS = [Item("f1", "인사청문경과보고서.hwp", 1024 * 1024), Item("f2", "알 수 없는 문서.hwp", 2048)]
FOLDERS = [Folder("d1", "인사청문_이형일", 44), Folder("d2", "20260917_전체위", 5)]


def test_moves_confident_files_and_leaves_the_rest(monkeypatch):
    state = setup(monkeypatch, items=ITEMS, folders=FOLDERS, moves=[
        {"file": "인사청문경과보고서.hwp", "folder": "인사청문_이형일", "reason": "인사청문 자료"},
        {"file": "알 수 없는 문서.hwp", "folder": "", "reason": "모르겠음"},
    ])

    out = run_sort.do_work(CFG, work(), lambda m: None)

    assert state["moved"] == [("f1", "ID-인사청문_이형일", "INBOX")]      # 확신 있는 것만 옮긴다
    assert out["counts"] == {"moved": 1, "skip": 1}
    assert out["tasks"]["move"] == (True, "1개 정리, 1개 보류")
    # 기록은 드라이브에만 남기고, 저장소에 남는 줄에는 파일 이름이 없다 (공개 저장소)
    folder, lines = state["log"][0]
    assert folder == "INBOX"
    assert any("인사청문경과보고서.hwp" in ln for ln in lines)
    assert any("수신함에 그대로" in ln for ln in lines)
    assert out["lines"] == ["재경위 1건 정리, 1건 보류"]
    for line in out["lines"]:
        assert "hwp" not in line and "인사청문_이형일" not in line


def test_new_folder_is_counted(monkeypatch):
    state = setup(monkeypatch, items=ITEMS[:1], folders=FOLDERS, moves=[
        {"file": "인사청문경과보고서.hwp", "folder": "20260920_인사청문", "reason": "새 회의"},
    ])

    out = run_sort.do_work(CFG, work(), lambda m: None)

    assert state["moved"] == [("f1", "ID-20260920_인사청문", "INBOX")]
    assert out["counts"]["new"] == 1


def test_dry_run_moves_nothing(monkeypatch):
    state = setup(monkeypatch, items=ITEMS, folders=FOLDERS, moves=[
        {"file": "인사청문경과보고서.hwp", "folder": "인사청문_이형일", "reason": "인사청문 자료"},
    ])

    out = run_sort.do_work(CFG, work(dry_run=True), lambda m: None)

    assert state["moved"] == [] and state["log"] == []
    assert out["counts"]["moved"] == 0


def test_empty_inbox_does_nothing(monkeypatch):
    state = setup(monkeypatch, items=[], folders=FOLDERS, moves=[])

    out = run_sort.do_work(CFG, work(), lambda m: None)

    assert state["llm"].asked == []              # 파일이 없으면 클로드를 부르지도 않는다
    assert out["skip_report"] is True
    assert out["counts"] == {"moved": 0, "skip": 0}


def test_prompt_gets_file_text(monkeypatch):
    state = setup(monkeypatch, items=ITEMS[:1], folders=FOLDERS, moves=[])

    run_sort.do_work(CFG, work(), lambda m: None)

    assert state["read"] == ["인사청문경과보고서.hwp"]
    assert "인사청문경과보고서.hwp 본문" in state["llm"].asked[0]
