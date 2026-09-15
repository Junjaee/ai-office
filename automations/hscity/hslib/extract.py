import os
import re
import zipfile

# 로컬 이름이 t 인 요소(<t>, <hp:t> 등)에 대응
_T_RE = re.compile(r"<(?:\w+:)?t\b[^>]*>(.*?)</(?:\w+:)?t>", re.S)


def extract_hwpx(path: str) -> str:
    """hwpx(zip) 내 section*.xml에서 <t>/<hp:t> 텍스트 추출."""
    texts = []
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if re.search(r"section\d+\.xml$", n, re.I)]
        if not names:
            names = [n for n in z.namelist() if n.lower().endswith(".xml")]
        for n in names:
            xml = z.read(n).decode("utf-8", errors="ignore")
            for t in _T_RE.findall(xml):
                clean = re.sub(r"<[^>]+>", "", t)
                if clean.strip():
                    texts.append(clean.strip())
    return "\n".join(texts)


def extract_pdf(path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(path)
    return "\n".join((pg.extract_text() or "") for pg in reader.pages)


def extract_hwp(path: str) -> str:
    """구 hwp 바이너리 best-effort (olefile). 실패 시 빈 문자열."""
    import olefile
    if not olefile.isOleFile(path):
        return ""
    ole = olefile.OleFileIO(path)
    try:
        parts = []
        for entry in ole.listdir():
            if entry and entry[0].startswith("BodyText"):
                data = ole.openstream(entry).read()
                text = data.decode("utf-16", errors="ignore")
                text = re.sub(r"[^가-힣 -~\n]", "", text)
                parts.append(text)
        return "\n".join(parts)
    finally:
        ole.close()


def extract_text(path: str) -> tuple[bool, str]:
    """확장자별 디스패치. (성공여부, 텍스트) 반환. 예외는 (False, '')."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".hwpx":
            return True, extract_hwpx(path)
        if ext == ".pdf":
            return True, extract_pdf(path)
        if ext == ".hwp":
            txt = extract_hwp(path)
            return (bool(txt.strip()), txt)
        if ext in (".txt", ".csv"):
            return True, open(path, encoding="utf-8", errors="ignore").read()
    except Exception:  # noqa: BLE001
        return False, ""
    return False, ""
