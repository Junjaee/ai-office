import os
import re

_ILLEGAL = re.compile(r'[\\/:*?"<>|\t\n]+')


def sanitize(name: str, maxlen: int = 60) -> str:
    s = _ILLEGAL.sub("_", name).strip().strip("_")
    if len(s) > maxlen:
        s = s[:maxlen]
    # Windows는 이름 끝의 공백/마침표를 허용하지 않으므로(잘린 뒤 남을 수 있음) 제거
    return s.rstrip(" ._") or "무제"


def _year(date: str) -> str:
    m = re.match(r"(\d{4})", date or "")
    return m.group(1) if m else "9999"


def post_dir(root: str, date: str, board_name: str, post_id: str,
             keyword: str, title: str) -> str:
    parts = [p for p in [date or "", post_id, keyword, title] if p]
    folder = sanitize("_".join(parts))
    return os.path.join(root, _year(date), board_name, folder)


def write_wonmun(dir_path: str, meta: dict) -> str:
    os.makedirs(dir_path, exist_ok=True)
    path = os.path.join(dir_path, "원문.md")
    md = (
        f"# {meta.get('title','')}\n\n"
        f"- 고시공고번호: {meta.get('reg_no','')}\n"
        f"- 게재일자: {meta.get('date','')}\n"
        f"- 담당부서: {meta.get('dept','')}\n"
        f"- 담당자/연락처: {meta.get('contact','')}\n"
        f"- 원문 링크: {meta.get('url','')}\n\n"
        f"## 본문\n\n{meta.get('body','')}\n"
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path
