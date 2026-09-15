import json
import os


def load_seen(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_seen(path: str, seen: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def is_new(seen: dict, board_id: str, post_id: str) -> bool:
    """숫자 ID는 크기 비교, 없으면 새 글로 간주."""
    last = seen.get(board_id)
    if last is None:
        return True
    try:
        return int(post_id) > int(last)
    except (TypeError, ValueError):
        # 비숫자 ID(gnews 등)는 사전식 비교. gnews id는 타임스탬프 접두라
        # 사전식 순서가 곧 시간 순서.
        return str(post_id) > str(last)
