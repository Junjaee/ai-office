"""예약 확인 — 지금 만들 주제가 있으면 true, 없으면 false 를 찍는다. 표준 라이브러리만 쓴다(워크플로가 의존성 설치 전에 부른다).
사용: python automations/insta/review_due.py --workspace side --automation insta_policy [--repo .]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import insta_review as review  # noqa: E402


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", default=".")
    p.add_argument("--workspace", default="side")
    p.add_argument("--automation", required=True)
    a = p.parse_args(argv)
    path = review.review_path(a.repo, a.workspace, a.automation)
    print("true" if review.has_due(path) else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
