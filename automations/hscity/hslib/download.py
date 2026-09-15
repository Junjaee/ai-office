import os
from urllib.parse import quote

from hslib.archive import sanitize

# encodeURI가 인코딩하지 않는 문자들
_ENCODE_URI_SAFE = "!#$&'()*+,-./:;=?@_~"


def _enc(s: str) -> str:
    return quote(s, safe=_ENCODE_URI_SAFE)


def build_download_url(base: str, user_file_nm: str, sys_file_nm: str, file_path: str) -> str:
    return (
        f"{base}?user_file_nm={_enc(user_file_nm)}"
        f"&sys_file_nm={_enc(sys_file_nm)}"
        f"&file_path={_enc(file_path)}"
    )


def download(session, base: str, att: dict, dest_dir: str) -> str:
    """첨부 다운로드 후 저장경로 반환. 실패 시 예외."""
    os.makedirs(dest_dir, exist_ok=True)
    url = build_download_url(base, att["user_file_nm"], att["sys_file_nm"], att["file_path"])
    r = session.get(url, timeout=60)
    r.raise_for_status()
    safe_name = sanitize(att["user_file_nm"] or "attachment", maxlen=120)
    dest = os.path.join(dest_dir, safe_name)
    with open(dest, "wb") as f:
        f.write(r.content)
    return dest


def download_attachment(session, cfg: dict, att: dict, dest_dir: str, referer: str = None) -> str:
    """att['kind']에 따라 다운로드 방식을 분기. 저장경로 반환.

    - kind == 'nd'  : bbs 계열 평문 앵커(ND_fileDownload.do) 직접 GET
    - 그 외(godownload): FileDown.jsp 방식(download())
    """
    os.makedirs(dest_dir, exist_ok=True)
    kind = att.get("kind", "godownload")
    if kind == "nd":
        href = att["href"]
        url = cfg["base_url"] + href if href.startswith("/") else href
        headers = {"Referer": referer} if referer else None
        r = session.get(url, timeout=60, headers=headers) if headers else session.get(url, timeout=60)
        r.raise_for_status()
        name = sanitize(att.get("user_file_nm") or "attachment", maxlen=120)
        dest = os.path.join(dest_dir, name)
        with open(dest, "wb") as f:
            f.write(r.content)
        return dest
    # default: goDownLoad → FileDown.jsp
    return download(session, cfg["download_base"], att, dest_dir)
