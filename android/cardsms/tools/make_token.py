# -*- coding: utf-8 -*-
"""카드문자 전달 앱용 구글 토큰 발급 — 지메일에 메일을 **넣기만** 하는 권한(gmail.insert).

가계부 토큰과 별개다. 브라우저가 열리면 계정 선택 → "확인되지 않은 앱" 고급 → 이동 → 허용.
결과는 개인 폴더 ai-home/01_가계부/카드문자전달-설정.json (커밋·채팅 금지). 값은 화면에 찍지 않는다.

    python android/cardsms/tools/make_token.py            # gmail.insert
    python android/cardsms/tools/make_token.py --modify   # 구글이 insert 동의를 막으면 가계부와 같은 gmail.modify
"""
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[3]
PERSONAL = REPO / "ai-home" / "01_가계부"
SECRET = PERSONAL / "client_secret.json"
OUT = PERSONAL / "카드문자전달-설정.json"

scope = "gmail.modify" if "--modify" in sys.argv else "gmail.insert"
SCOPES = [f"https://www.googleapis.com/auth/{scope}"]

if not SECRET.exists():
    raise SystemExit(f"client_secret.json 이 없습니다: {SECRET}")

print(f">>> 브라우저가 열립니다. 권한: {scope} (메일 넣기)")
flow = InstalledAppFlow.from_client_secrets_file(str(SECRET), SCOPES)
creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")
if not creds.refresh_token:
    raise SystemExit("리프레시 토큰이 없습니다. 동의 화면에서 허용했는지 확인하세요.")

info = json.load(open(SECRET, encoding="utf-8"))
info = info.get("installed") or info.get("web")
OUT.write_text(json.dumps({
    "client_id": info["client_id"],
    "client_secret": info["client_secret"],
    "refresh_token": creds.refresh_token,
    "subject": "[카드SMS]",
    "keywords": ["승인", "취소"],
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(">>> 완료:", OUT)
print(">>> 부여된 권한:", " ".join(creds.scopes or []))
