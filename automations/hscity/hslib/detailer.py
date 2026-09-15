from bs4 import BeautifulSoup
from hslib.adapters import get_adapter
from hslib import detail as detail_mod


def _gnews_body(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    div = soup.select_one("div.gallery_view_con")
    return div.get_text("\n", strip=True) if div else ""


def fetch_detail(session, cfg, board, post_id):
    """상세 페이지를 3개 게시판 계열 공통으로 조회/파싱.

    반환: (detail_dict, detail_url)
    detail_dict keys: title, reg_no, date, dept, contact, body,
                      attachments(kind 태깅된 dict 리스트).
    """
    adapter = get_adapter(board["adapter"])
    base = cfg["base_url"]
    url = adapter.detail_url(board, base, post_id)

    if board["adapter"] == "gnews":
        data = {"q_beCode": board["be_code"], board["id_param"]: post_id}
        r = session.post(base + board["detail_path"], data=data, timeout=30)
        html = r.text
        d = detail_mod.parse_detail(html)
        d["body"] = _gnews_body(html)
        d["attachments"] = []
        if not d.get("title"):
            d["title"] = _gnews_title(html)
        return d, url

    r = session.get(url, timeout=30)
    html = r.text
    d = detail_mod.parse_detail(html)
    if board["adapter"] == "bbs":
        d["attachments"] = detail_mod.parse_nd_attachments(html)
    return d, url


def _gnews_title(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for sel in ("div.gallery_view_wrap h3", "div.board_view h3", "h3", "h4"):
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    return ""
