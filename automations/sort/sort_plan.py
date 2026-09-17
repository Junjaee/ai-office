"""수신함 정리 — 어느 폴더로 옮길지 정하는 부분 (클로드에게 묻고, 답을 검사한다).

계획은 파일마다 {"file": 이름, "folder": 폴더 이름, "reason": 한 줄} 이고,
folder 가 빈 문자열이면 "모르겠음" → 수신함에 그대로 둔다(잘못 옮기느니 두는 편이 낫다).
"""
from __future__ import annotations

SYSTEM = """너는 국회 의원실 보좌진의 자료 정리를 돕는다.
위원회 폴더 안에는 회의·행사마다 폴더가 있다(예: 20260917_전체위, 20260917_공청회, 인사청문_이형일).
수신함에 새로 들어온 파일을 알맞은 폴더로 옮기는 것이 네 일이다.

규칙:
- 되도록 이미 있는 폴더를 쓴다. 이름이 정확히 일치해야 한다.
- 딱 맞는 폴더가 없고 새 회의·행사 자료가 분명할 때만 새 폴더를 제안한다.
  이름은 기존 방식을 따른다: 회의는 YYYYMMDD_전체위 / YYYYMMDD_공청회 / YYYYMMDD_소위,
  인사청문은 인사청문_<후보자 이름>.
- 어디에 둘지 확신이 없으면 folder 를 빈 문자열("")로 둔다. 그러면 수신함에 그대로 남는다.
  애매한 것을 억지로 옮기지 마라.
- reason 은 한국어 한 줄(30자 안쪽)로 근거를 적는다.
- 파일 이름과 본문 앞부분을 함께 보고 판단한다. 날짜는 본문에 적힌 회의 날짜를 우선한다.

답은 아래 형태의 JSON 하나로만 한다. 설명·인사말은 쓰지 마라.
{"moves": [
  {"file": "파일 이름 그대로", "folder": "옮길 폴더 이름", "reason": "근거 한 줄"},
  {"file": "애매한 파일", "folder": "", "reason": "어느 회의인지 불분명"}
]}"""

_MOVE = {
    "type": "object",
    "required": ["file", "folder", "reason"],
    "properties": {"file": {"type": "string"}, "folder": {"type": "string"}, "reason": {"type": "string"}},
}
# 배열로 답하는 모델도 있어 둘 다 받는다 (2026-09-17 실제로 배열이 왔다)
SCHEMA = {"anyOf": [
    {"type": "object", "required": ["moves"], "properties": {"moves": {"type": "array", "items": _MOVE}}},
    {"type": "array", "items": _MOVE},
]}


def build_prompt(committee: str, folders: list, files: list[tuple[str, int, str]],
                 rules: list[str] | None = None) -> str:
    """committee: 위원회 이름, folders: Folder 목록, files: (이름, 크기KB, 본문앞부분),
    rules: 이 위원회에만 적용할 추가 규칙(설정 파일의 `rules`). 일반 규칙보다 우선한다."""
    lines = [f"위원회: {committee}", "", "## 이미 있는 폴더"]
    lines += [f"- {f.name} (안에 {f.count}개)" for f in folders] or ["- (없음)"]
    if rules:
        lines += ["", "## 꼭 지킬 규칙 (위의 일반 규칙보다 우선)"]
        lines += [f"- {r}" for r in rules]
    lines += ["", "## 수신함에 있는 파일"]
    for name, kb, text in files:
        lines.append(f"### {name} ({kb}KB)")
        lines.append(text[:1200] if text else "(내용을 읽지 못했습니다. 이름으로 판단하세요.)")
        lines.append("")
    lines.append("각 파일을 어느 폴더로 옮길지 정해 JSON 으로 답하라.")
    return "\n".join(lines)


def clean_plan(plan: dict | list, file_names: list[str], folder_names: list[str],
               allow_new: bool = True) -> list[dict]:
    """클로드 답을 검사해 실제로 옮길 것만 남긴다.

    - 모르는 파일 이름은 버린다(멋대로 만든 이름 방지).
    - folder 가 비었으면 건너뛴다(수신함에 둠).
    - 기존 폴더가 아니면 allow_new 일 때만 새 폴더로 인정한다. 새 폴더 이름은 한 단계만(슬래시 금지).
    - 한 파일이 여러 번 나오면 처음 것만 쓴다.
    """
    rows = plan if isinstance(plan, list) else (plan.get("moves") or [])
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = (row.get("file") or "").strip()
        folder = (row.get("folder") or "").strip()
        reason = " ".join((row.get("reason") or "").split())[:60]
        if name not in file_names or name in seen or not folder:
            continue
        if "/" in folder or folder.startswith("."):
            continue
        is_new = folder not in folder_names
        if is_new and not allow_new:
            continue
        seen.add(name)
        out.append({"file": name, "folder": folder, "reason": reason, "new": is_new})
    return out
