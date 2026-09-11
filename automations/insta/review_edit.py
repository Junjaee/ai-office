"""예약 수정(표준 라이브러리만) — 사이트에서 예약 항목을 취소하거나 시각을 바꾼다. 워크플로 mode=edit 가 의존성 설치 없이 부른다.

사용: python review_edit.py --workspace side --automation insta_aitips --edits "0123abcd=cancel,89ef0123=15:30,4567cdef=2026-09-13T07:30"
  id=cancel      예약 취소 (queued 만)
  id=HH:MM       다음에 오는 그 시각(KST). 이미 지난 시각이면 내일
  id=ISO 시각     그 시각으로
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import insta_review as review  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="side")
    ap.add_argument("--automation", required=True)
    ap.add_argument("--edits", required=True)
    args = ap.parse_args()
    repo = Path(__file__).resolve().parent.parent.parent
    path = review.review_path(repo, args.workspace, args.automation)
    data = review.load(path)
    now = datetime.now(timezone.utc)
    data, changed = review.apply_edits(data, review.parse_edits(args.edits), now=now)
    if not changed:
        print("바뀐 것 없음 (id 가 없거나 이미 끝난 항목)")
        return 0
    review.save(path, data)
    for c in changed:
        print(c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
