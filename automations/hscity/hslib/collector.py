from hslib import state


def collect_new(board, adapter, seen, base_url, fetch_list, max_pages=5):
    """Return NEW post rows (newest-first) across pages, stopping once a already-seen
    post is reached (list is newest-first, so everything after is older)."""
    out = []
    seen_ids = set()  # 이번 실행 내 중복 방지(페이징이 같은 글을 다시 줘도 한 번만)
    for page in range(1, max_pages + 1):
        html = fetch_list(base_url + adapter.list_url(board, page))
        rows = adapter.parse_list(html)
        if not rows:
            break
        hit_seen = False
        for row in rows:
            pid = row["post_id"]
            if not state.is_new(seen, board["id"], pid):
                hit_seen = True
                break
            if pid in seen_ids:
                continue
            seen_ids.add(pid)
            out.append(row)
        if hit_seen:
            break
    return out
