import re
from bs4 import BeautifulSoup
from .base import BoardAdapter

_SN_RE = re.compile(r"q_bbscttSn=(\d+)")


def parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("table tbody tr"):
        a = tr.select_one("a[href*=q_bbscttSn]")
        if not a:
            continue
        href = (a.get("href", "") or "") + " " + (a.get("onclick", "") or "")
        m = _SN_RE.search(href)
        if not m:
            continue
        tds = tr.find_all("td")
        rows.append({
            "post_id": m.group(1),
            "title": a.get_text(strip=True),
            "reg_no": "",
            "dept": tds[-2].get_text(strip=True) if len(tds) >= 2 else "",
            "date": tds[-1].get_text(strip=True) if len(tds) >= 1 else "",
        })
    return rows


class BbsAdapter(BoardAdapter):
    def parse_list(self, html: str) -> list[dict]:
        return parse_list(html)

    def list_url(self, board: dict, page: int) -> str:
        return f"{board['list_path']}?q_bbsCode={board['bbs_code']}&q_currPage={page}"

    def detail_url(self, board: dict, base_url: str, post_id: str) -> str:
        return (f"{base_url}{board['detail_path']}"
                f"?q_bbsCode={board['bbs_code']}&q_bbscttSn={post_id}")
