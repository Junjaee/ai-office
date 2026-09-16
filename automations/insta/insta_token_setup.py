"""게시 토큰(Instagram 로그인 방식) 교체 도우미 — 토큰 값을 화면·채팅에 찍지 않고 (1) 형식 확인 (2) 장기 토큰(60일) 교환 (3) 권한 시험 (4) GitHub Secrets 등록까지 한다.

사용:
  python automations/insta/insta_token_setup.py <토큰 파일> [--app-secret-file ai-side/.../app_secret.txt] [--account aitips] [--set-secret]
  - 토큰 파일: Meta 앱 "Instagram 로그인이 포함된 API 설정"에서 만든 토큰을 그대로 붙여 넣은 txt (개인 폴더, 커밋 금지)
  - --app-secret-file 을 주면 단기 토큰(1시간)을 장기 토큰(60일)으로 바꿔 <토큰 파일>.long 에 저장한다. 이미 장기 토큰이면 그대로 쓴다.
  - 권한 시험: 기본 조회(/me) → 댓글 읽기(instagram_business_manage_comments) → 대화 목록(instagram_business_manage_messages).
  - --set-secret 이면 `gh secret set INSTA_<계정>_TOKEN` 으로 저장소 비밀값에 넣는다(값은 파이프로만 전달).
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import requests

GRAPH = "https://graph.instagram.com/v23.0"
UA = {"User-Agent": "ai-office-insta/1.0"}


def read_secret(path: str) -> str:
    return re.sub(r"\s+", "", Path(path).read_text(encoding="utf-8-sig"))


def get(path: str, token: str, **params) -> tuple[bool, dict]:
    r = requests.get(f"{GRAPH}/{path}", params={**params, "access_token": token}, headers=UA, timeout=30)
    try:
        data = r.json()
    except ValueError:
        data = {"raw": r.text[:200]}
    return r.ok and "error" not in data, data


def err_text(data: dict) -> str:
    e = data.get("error", {})
    return f"{e.get('message', data)} (code {e.get('code')}, sub {e.get('error_subcode')})"[:200]


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("token_file")
    ap.add_argument("--app-secret-file", default="")
    ap.add_argument("--account", default="policy")
    ap.add_argument("--set-secret", action="store_true")
    a = ap.parse_args(argv)
    token = read_secret(a.token_file)
    print(f"토큰 길이 {len(token)}자, 앞 4자 {token[:4]}…")
    if len(token) < 100 or " " in token:
        print("→ 토큰 같지 않습니다. 브라우저에 뜬 코드가 아니라 '액세스 토큰 생성' 결과(IGAA… 로 시작하는 긴 문자열)를 통째로 저장해 주세요.")
        return 1

    # 1) 기본 조회
    ok, me = get("me", token, fields="user_id,username")
    if not ok:
        print("기본 조회 실패:", err_text(me)); return 1
    print(f"계정 확인: @{me.get('username')} (id {me.get('user_id')})")

    # 2) 장기 토큰 교환 (단기 토큰이면)
    if a.app_secret_file:
        r = requests.get(f"{GRAPH.rsplit('/v', 1)[0]}/access_token", params={"grant_type": "ig_exchange_token",
                         "client_secret": read_secret(a.app_secret_file), "access_token": token}, headers=UA, timeout=30)
        if r.ok and "access_token" in r.json():
            token = r.json()["access_token"]
            out = Path(a.token_file + ".long")
            out.write_text(token, encoding="utf-8")
            print(f"장기 토큰(약 {int(r.json().get('expires_in', 0)) // 86400}일) 저장: {out.name}")
        else:
            print("장기 교환 건너뜀(이미 장기 토큰이거나 실패):", r.text[:120])

    # 3) 권한 시험
    ok, media = get("me/media", token, fields="id", limit=1)
    if not ok:
        print("게시물 목록 실패(instagram_business_basic 필요):", err_text(media)); return 1
    mid = (media.get("data") or [{}])[0].get("id")
    if mid:
        ok, c = get(f"{mid}/comments", token, fields="id", limit=1)
        print("댓글 읽기 권한(instagram_business_manage_comments):", "OK" if ok else "없음 — " + err_text(c))
    ok, conv = get("me/conversations", token, platform="instagram", limit=1)
    print("메시지 권한(instagram_business_manage_messages):", "OK" if ok else "없음 — " + err_text(conv))
    if not ok:
        print("→ 앱의 'Instagram 로그인이 포함된 API 설정' 권한에서 instagram_business_manage_messages 를 켜고 토큰을 다시 만드세요. "
              "인스타 앱 설정 → 메시지 및 스토리 답장 → 메시지 관리 → '연결된 도구' 접근 허용도 켜야 합니다.")
        return 2

    # 4) GitHub Secrets
    if a.set_secret:
        name = f"INSTA_{a.account.upper()}_TOKEN"
        p = subprocess.run(["gh", "secret", "set", name], input=token, text=True, capture_output=True)
        print(f"GitHub Secret {name}:", "등록됨" if p.returncode == 0 else "실패 " + p.stderr[:200])
        return 0 if p.returncode == 0 else 1
    print("모든 권한 OK. --set-secret 을 붙여 다시 실행하면 GitHub Secrets 에 등록합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
