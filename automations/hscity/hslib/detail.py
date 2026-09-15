import re
from bs4 import BeautifulSoup

_DL_RE = re.compile(
    r"goDownLoad\('(?P<user>[^']*)',\s*'(?P<sys>[^']*)',\s*'(?P<path>[^']*)'\)"
)

_LABELS = {
    "제목": "title",
    "고시공고번호": "reg_no",
    "게재(공고)일자": "date",
    "담당부서": "dept",
    "담당자/연락처": "contact",
    # bbs 게시판(타기관 공고/고시, 시정알림방, 반상회보) 전용 라벨
    "등록일시": "date",
    "담당자": "contact",
}


def parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    out = {"title": "", "reg_no": "", "date": "", "dept": "",
           "contact": "", "body": "", "attachments": []}

    # gosi는 행마다 th/td가 1쌍, bbs는 한 행에 th/td/th/td가 여러 쌍 → th마다 다음 td를 짝짓는다
    for th in soup.select("tr th"):
        td = th.find_next_sibling("td")
        if not td:
            continue
        label = th.get_text(strip=True)
        key = _LABELS.get(label)
        if key:
            out[key] = td.get_text(" ", strip=True)
        if label == "내용":
            out["body"] = td.get_text("\n", strip=True)

    for a in soup.select("a[href*=goDownLoad]"):
        m = _DL_RE.search(a.get("href", ""))
        if m:
            out["attachments"].append({
                "kind": "godownload",
                "user_file_nm": m.group("user"),
                "sys_file_nm": m.group("sys"),
                "file_path": m.group("path"),
            })
    return out


def parse_nd_attachments(html: str) -> list[dict]:
    """bbs 게시판 첨부(ND_fileDownload.do 앵커) 파싱.

    goDownLoad 방식이 아닌 평문 앵커 링크를 사용하는 bbs 계열 전용.
    detailer 가 필요 시점에 직접 호출한다(gosi 페이지에는 적용하지 않음).
    """
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.select('a[href*="ND_fileDownload.do"]'):
        href = a.get("href", "")
        if not href:
            continue
        out.append({
            "kind": "nd",
            "user_file_nm": a.get_text(strip=True),
            "href": href,
        })
    return out
