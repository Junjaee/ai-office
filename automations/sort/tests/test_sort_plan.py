"""수신함 정리 — 클로드 답 검사(순수 함수, 네트워크 없음)."""
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sort_plan import build_prompt, clean_plan  # noqa: E402

FILES = ["인사청문경과보고서.hwp", "공청회 자료집.pdf", "알 수 없는 문서.hwp"]
FOLDERS = ["20260917_공청회", "20260917_전체위", "인사청문_이형일"]


@dataclass
class F:
    id: str
    name: str
    count: int


def plan(*rows):
    return {"moves": list(rows)}


def test_keeps_only_known_files_and_folders():
    got = clean_plan(plan(
        {"file": "인사청문경과보고서.hwp", "folder": "인사청문_이형일", "reason": "인사청문 자료"},
        {"file": "없는 파일.hwp", "folder": "20260917_전체위", "reason": "지어낸 이름"},
    ), FILES, FOLDERS)
    assert [m["file"] for m in got] == ["인사청문경과보고서.hwp"]
    assert got[0]["new"] is False


def test_empty_folder_means_leave_it_in_inbox():
    """확신이 없으면 옮기지 않는다 — 잘못 옮기느니 두는 편이 낫다."""
    got = clean_plan(plan({"file": "알 수 없는 문서.hwp", "folder": "", "reason": "모르겠음"}), FILES, FOLDERS)
    assert got == []


def test_new_folder_is_marked_and_can_be_forbidden():
    rows = plan({"file": "공청회 자료집.pdf", "folder": "20260920_소위", "reason": "새 회의"})
    got = clean_plan(rows, FILES, FOLDERS)
    assert got[0]["new"] is True and got[0]["folder"] == "20260920_소위"
    assert clean_plan(rows, FILES, FOLDERS, allow_new=False) == []


def test_rejects_paths_and_duplicates():
    got = clean_plan(plan(
        {"file": "공청회 자료집.pdf", "folder": "20260917_공청회/하위", "reason": "경로는 금지"},
        {"file": "인사청문경과보고서.hwp", "folder": "인사청문_이형일", "reason": "첫 번째"},
        {"file": "인사청문경과보고서.hwp", "folder": "20260917_전체위", "reason": "두 번째는 무시"},
    ), FILES, FOLDERS)
    assert [(m["file"], m["folder"]) for m in got] == [("인사청문경과보고서.hwp", "인사청문_이형일")]


def test_accepts_bare_array_answer():
    """모델이 {"moves": [...]} 대신 배열만 답해도 받아들인다 (2026-09-17 실제로 그랬다)."""
    rows = [{"file": "공청회 자료집.pdf", "folder": "20260917_공청회", "reason": "공청회 자료"}]
    assert clean_plan(rows, FILES, FOLDERS) == clean_plan({"moves": rows}, FILES, FOLDERS)
    assert clean_plan(["문자열은 무시"], FILES, FOLDERS) == []


def test_prompt_shows_folders_and_file_text():
    text = build_prompt("재경위", [F("1", "20260917_공청회", 7)],
                        [("자료집.pdf", 804, "제439회국회 공청회 자료")])
    assert "위원회: 재경위" in text
    assert "- 20260917_공청회 (안에 7개)" in text
    assert "### 자료집.pdf (804KB)" in text and "제439회국회 공청회 자료" in text
    assert "꼭 지킬 규칙" not in text          # 규칙이 없으면 그 자리도 없다


def test_prompt_carries_user_rules():
    """사용자가 정한 규칙(예: 국정감사 자료는 _참고자료)을 프롬프트에 싣는다 — 2026-09-17."""
    text = build_prompt("재경위", [F("1", "_참고자료", 3)], [("국정감사계획서.hwp", 40, "")],
                        rules=["국정감사 관련 자료는 `_참고자료` 폴더로 옮긴다."])
    assert "## 꼭 지킬 규칙 (위의 일반 규칙보다 우선)" in text
    assert "- 국정감사 관련 자료는 `_참고자료` 폴더로 옮긴다." in text
