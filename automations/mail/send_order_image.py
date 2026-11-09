"""질의순서 한글 파일 → 이미지 → 텔레그램.

run_mail.py 가 /tmp/order 에 받아 둔 한글 파일을 원본 양식 그대로 이미지로 바꿔 보낸다.
LibreOffice(+H2Orestart)와 글꼴이 깔린 실행에서만 부른다 — mail.yml 이 질의순서가 있을 때만 깐다.

사용: python send_order_image.py [--config 경로] [--dir 폴더] [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from telegram_bot import send_document, send_photo, telegram_env  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mail_hwp import convert  # noqa: E402

HERE = Path(__file__).resolve().parent
CHAT_KEY = "NOTICE_530_CHAT_ID"
TOKEN_KEY = "NOTICE_530_BOT_TOKEN"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description="질의순서 이미지 보내기")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"))
    p.add_argument("--dir", default="/tmp/order", help="한글 파일이 있는 폴더")
    p.add_argument("--dry-run", action="store_true", help="보내지 않고 이미지만 만든다")
    args = p.parse_args(argv)

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    src = Path(args.dir)
    files = sorted(src.glob("*.hwp")) + sorted(src.glob("*.hwpx"))
    if not files:
        print("질의순서 파일 없음")
        return 0

    # 사진으로 보내면 채팅에 바로 펼쳐 보인다. 글자가 작아 흐리면 "document" 로 바꾼다
    as_photo = (cfg.get("order_send_as") or "photo").strip() == "photo"
    highlight = (cfg.get("order_highlight") or "").strip()
    color = (cfg.get("order_color") or "#FF7210").strip()
    token, chat = ("", "")
    if not args.dry_run:
        token, chat = telegram_env(CHAT_KEY, TOKEN_KEY)

    sent = failed = skipped = 0
    for hwp in files:
        try:
            images = convert(hwp, src, highlight, color)
        except Exception as exc:  # noqa: BLE001 - 한 파일이 실패해도 나머지는 보낸다
            print(f"  · 변환 실패 {hwp.name} — {type(exc).__name__}", file=sys.stderr)
            failed += 1
            continue
        if not images:
            print(f"  · {hwp.name} → '{highlight}' 없음, 보내지 않음")
            skipped += 1
            continue
        print(f"  · {hwp.name} → 이미지 {len(images)}장")
        for img in images:
            if args.dry_run:
                continue
            send = send_photo if as_photo else send_document
            send(token, chat, img.name, img.read_bytes(), timeout=int(cfg.get("timeout") or 60))
            sent += 1
    print(f"질의순서 {len(files)}건, 이미지 전송 {sent}장"
          + (f", 건너뜀 {skipped}건" if skipped else "")
          + (f", 실패 {failed}건" if failed else ""))
    return 1 if failed and not sent else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
