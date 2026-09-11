"""(로컬 1회용) Google OAuth 동의 화면을 열어 리프레시 토큰을 만든다.

사용:
    python automations/common/google_auth.py <client_secret.json 경로> <출력 파일 경로>

출력 파일에는 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN 세 줄이
KEY=VALUE 형식으로 저장된다. 화면에는 값이 표시되지 않는다.
이 파일은 GitHub Secrets에 넣은 뒤 지운다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 공용 토큰 권한 — 모든 자동화가 GOOGLE_* 하나를 함께 쓴다. 권한을 더할 때는 이 목록에 넣고 다시 발급한다
# (빼면 그 권한을 쓰는 자동화가 멈춘다: 드라이브=회의록·기사, 지메일·시트=가계부, 캘린더=주말 일정)
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def main(secret_path: str, out_path: str) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not creds.refresh_token:
        raise SystemExit("리프레시 토큰이 발급되지 않았습니다. 동의 화면에서 접근을 허용했는지 확인하세요.")
    client = json.loads(Path(secret_path).read_text(encoding="utf-8"))
    info = client.get("installed") or client.get("web")
    Path(out_path).write_text(
        f"GOOGLE_CLIENT_ID={info['client_id']}\nGOOGLE_CLIENT_SECRET={info['client_secret']}\n"
        f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}\n",
        encoding="utf-8",
    )
    print(f"저장 완료: {out_path} (값은 표시하지 않음)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
