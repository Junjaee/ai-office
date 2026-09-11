"""참고 계정 읽기(비즈니스 디스커버리) 준비 확인 — 토큰 파일을 읽어 (1) 장기 토큰으로 바꾸고 (2) 페이지에 연결된 인스타 계정 id 를 찾고
(3) 참고 계정 하나를 시험 조회한다. 토큰 값은 화면에 찍지 않는다.

사용: python automations/insta/discovery_setup.py <토큰 파일> [--app-id ID --app-secret-file 파일] [--test ai.trend.kr]
  - 장기 토큰 교환(--app-id/--app-secret-file)을 주면 60일짜리로 바꿔 <토큰 파일>.long 에 저장한다.
  - 마지막 줄에 IG_DISCOVERY_USER_ID 값을 찍는다 (비밀값 아님).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import requests

GRAPH = "https://graph.facebook.com/v23.0"


def read_secret(path: str) -> str:
    return re.sub(r"\s+", "", Path(path).read_text(encoding="utf-8-sig"))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("token_file")
    ap.add_argument("--app-id", default="")
    ap.add_argument("--app-secret-file", default="")
    ap.add_argument("--test", default="ai.trend.kr")
    a = ap.parse_args(argv)
    token = read_secret(a.token_file)
    print(f"토큰 길이 {len(token)}자")

    if a.app_id and a.app_secret_file:
        r = requests.get(f"{GRAPH}/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": a.app_id,
            "client_secret": read_secret(a.app_secret_file), "fb_exchange_token": token}, timeout=30)
        if not r.ok:
            print("장기 토큰 교환 실패:", r.status_code, r.text[:200]); return 1
        token = r.json()["access_token"]
        Path(a.token_file + ".long").write_text(token, encoding="utf-8")
        print(f"장기 토큰 저장: {a.token_file}.long (만료 약 {r.json().get('expires_in', 0) // 86400}일 뒤)")

    r = requests.get(f"{GRAPH}/me/accounts", params={"fields": "name,instagram_business_account", "access_token": token}, timeout=30)
    if not r.ok:
        print("페이지 조회 실패:", r.status_code, r.text[:200]); return 1
    pages = r.json().get("data", [])
    linked = [(p["name"], p["instagram_business_account"]["id"]) for p in pages if p.get("instagram_business_account")]
    print(f"페이지 {len(pages)}개, 인스타 연결된 페이지 {len(linked)}개")
    if not linked:
        print("인스타 프로페셔널 계정이 연결된 페이지가 없습니다. 페이지 설정 → 연결된 계정 → Instagram 에서 연결하세요."); return 1
    name, ig_id = linked[0]
    print(f"페이지 '{name}' → 인스타 계정 id {ig_id}")

    if a.test:
        fields = f"business_discovery.username({a.test}){{followers_count,media_count,media.limit(3){{caption,like_count,timestamp}}}}"
        r = requests.get(f"{GRAPH}/{ig_id}", params={"fields": fields, "access_token": token}, timeout=30)
        if not r.ok:
            print(f"@{a.test} 조회 실패:", r.status_code, r.text[:200]); return 1
        bd = r.json().get("business_discovery", {})
        print(f"@{a.test}: 팔로워 {bd.get('followers_count')} · 게시물 {bd.get('media_count')} · 최근 3건 좋아요 "
              + ", ".join(str(m.get("like_count")) for m in bd.get("media", {}).get("data", [])))
    print(f"\nIG_DISCOVERY_USER_ID={ig_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
