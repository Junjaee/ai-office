"""지출·정산 자동화 — 카드 승인문자(Gmail 전달)를 가계부 시트에 날짜순 자동 반영.

사용:
  python run_ledger.py              # 실제 실행 (끝나면 상태 파일 커밋·push)
  python run_ledger.py --dry-run    # 시트에 쓰지 않고 파싱·요약만

인증(둘 중 하나):
  - GitHub Actions: 환경변수 GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN
  - 로컬 시험: 이 파일 옆(또는 --token) token.json (개인 폴더에서 복사). 커밋 금지.

do_work() 하나만 실제 작업이고 나머지 프레임워크는 템플릿 그대로.
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import sys
import time
import traceback
import datetime as dt
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from errors import to_korean  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:
    report_status = None

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

KST = dt.timezone(dt.timedelta(hours=9))
AUTOMATION_ID = "ledger"
AUTOMATION_NAME = "지출·정산"
DEPT = "research"
HERE = Path(__file__).resolve().parent

# ───────────────────────── 가계부 설정 (비밀 아님) ─────────────────────────
SCOPES = ["https://www.googleapis.com/auth/gmail.modify",
          "https://www.googleapis.com/auth/spreadsheets"]
SPREADSHEET_ID = "1A36RI04614y4ZPGE01gRVy_aIIoblg1XPVErcfNtzkg"
MONTH_TAB = {"2026-07": "2026년 7월", "2026-08": "2026년 8월", "2026-09": "2026년 9월"}
GMAIL_QUERY = 'subject:"[카드SMS]" newer_than:2d'
PROCESSED_LABEL = "카드동기화완료"
COL_DATE, COL_AMOUNT = "B", "F"
DATA_FIRST_ROW, DATA_SCAN_LAST_ROW = 6, 250
BF_START, BF_END = 1, 6   # B..F (0-based, end 배타적)

CARD_DETECT = [("현대", "현대카드"), ("삼성", "삼성카드"), ("우리", "우리카드"),
               ("국민", "쿠팡와우카드"), ("KB", "쿠팡와우카드"), ("쿠팡", "쿠팡와우카드")]
DEFAULT_CARD = "현대카드"
CATEGORY_RULES = [
    ("식비", ["스타벅스", "컴포즈", "메가", "투썸", "커피", "배달의민족", "쿠팡이츠", "버거킹",
             "맥도날드", "치킨", "김밥", "분식", "식당", "떡볶", "베이커리", "파리바게", "던킨",
             "트레이더스", "이마트", "노브랜드", "GS25", "씨유", "CU", "회관", "한식", "중식",
             "일식", "양식", "food", "푸드", "곱창", "고기", "국밥", "칼국수", "냉면", "피자",
             "족발", "보쌈", "횟집", "포차", "주점"]),
    ("기타", ["주유", "에너지", "칼텍스", "SK에너지", "GS칼텍스", "고속도로", "통행료",
             "하이패스", "주차", "병원", "의원", "약국", "면세"]),
    ("생활비", ["쿠팡", "지마켓", "G마켓", "다이소", "네이버페이", "올리브영", "쿠팡플레이",
              "구글", "넷플릭스", "티빙"]),
    ("우빈식비", ["분유", "이유식", "떡뻥", "퓨레"]),
    ("우빈생활비", ["문화센터", "문센", "키즈", "하이엔"]),
]
DEFAULT_ITEM = "생활비"
IGNORE_KEYWORDS = ["거절", "승인거절", "환불", "청구", "출금", "안내", "한도"]

AMOUNT_RE = re.compile(r"^([\d,]{2,})\s*원")
PAYTYPE_RE = re.compile(r"(일시불|\d+개월|할부)")
DATE_LINE_RE = re.compile(r"(\d{1,2})/(\d{1,2})\s+\d{1,2}:\d{2}")
EXCLUDE_AMOUNT = ("누적", "잔여", "한도", "가능")


# ───────────────────────── 인증 ─────────────────────────
def get_services(token_path: str | None):
    cid, csec, rtok = (os.environ.get("GOOGLE_CLIENT_ID"),
                       os.environ.get("GOOGLE_CLIENT_SECRET"),
                       os.environ.get("GOOGLE_REFRESH_TOKEN"))
    if cid and csec and rtok:                    # GitHub Actions: 환경변수
        # 리프레시 토큰 갱신에는 scope 를 넣지 않는다(넣으면 invalid_scope). 발급 시 부여된 scope 로 갱신됨.
        creds = Credentials(None, refresh_token=rtok, client_id=cid, client_secret=csec,
                            token_uri="https://oauth2.googleapis.com/token")
    elif token_path and os.path.exists(token_path):   # 로컬 시험: token.json
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    else:
        raise SystemExit("인증 정보 없음: GitHub Secrets(GOOGLE_*) 또는 로컬 token.json 필요")
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds), build("sheets", "v4", credentials=creds)


# ───────────────────────── Gmail ─────────────────────────
def ensure_label(gmail):
    for l in gmail.users().labels().list(userId="me").execute().get("labels", []):
        if l["name"] == PROCESSED_LABEL:
            return l["id"]
    return gmail.users().labels().create(
        userId="me", body={"name": PROCESSED_LABEL}).execute()["id"]


def fetch_messages(gmail):
    q = f'{GMAIL_QUERY} -label:{PROCESSED_LABEL}'
    return gmail.users().messages().list(userId="me", q=q).execute().get("messages", [])


def get_body_text(gmail, msg_id):
    payload = gmail.users().messages().get(userId="me", id=msg_id, format="full").execute()["payload"]

    def walk(part):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "ignore")
        for p in part.get("parts", []) or []:
            if (t := walk(p)):
                return t
        return ""

    text = walk(payload)
    if not text and payload.get("body", {}).get("data"):
        text = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", "ignore")
    return text


# ───────────────────────── 파싱 ─────────────────────────
def detect_card(header):
    for key, name in CARD_DETECT:
        if key in header:
            return name
    return DEFAULT_CARD


def classify_item(detail):
    for item, keys in CATEGORY_RULES:
        if any(k in detail for k in keys):
            return item
    return DEFAULT_ITEM


def parse_sms(text, received_date):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    joined = "\n".join(lines)
    if "승인" not in joined and "취소" not in joined:
        return None
    if any(k in joined for k in IGNORE_KEYWORDS):
        return None
    kind = "cancel" if "취소" in joined else "approve"
    header = next((l for l in lines if "승인" in l or "취소" in l), joined)

    amount = None
    for l in lines:
        if any(k in l for k in EXCLUDE_AMOUNT):
            continue
        if (m := AMOUNT_RE.match(l)):
            amount = int(m.group(1).replace(",", ""))
            break
    if not amount:
        return None
    pt = PAYTYPE_RE.search(joined)
    pay_type = pt.group(1) if pt else ""

    month = day = None
    detail = ""
    for i, l in enumerate(lines):
        if (dm := DATE_LINE_RE.search(l)):
            month, day = int(dm.group(1)), int(dm.group(2))
            for nxt in lines[i + 1:]:
                if any(k in nxt for k in EXCLUDE_AMOUNT):
                    continue
                if AMOUNT_RE.match(nxt) or nxt in ("일시불", "할부"):
                    continue
                if "승인" in nxt or "발신" in nxt or "님" in nxt:
                    continue
                detail = nxt
                break
            break
    if month is None:
        month, day = received_date.month, received_date.day
    if not detail:
        detail = "카드결제"
    if pay_type and pay_type != "일시불":
        detail = f"{detail} ({pay_type})"
    return {"month": month, "day": day, "detail": detail, "amount": amount,
            "card": detect_card(header), "pay_type": pay_type, "kind": kind}


# ───────────────────────── 시트 ─────────────────────────
def get_sheet_id(sheets, tab_name):
    for sh in sheets.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()["sheets"]:
        if sh["properties"]["title"] == tab_name:
            return sh["properties"]["sheetId"]
    raise RuntimeError(f"탭을 찾을 수 없음: {tab_name}")


def read_days(sheets, tab_name):
    rng = f"'{tab_name}'!{COL_DATE}{DATA_FIRST_ROW}:{COL_AMOUNT}{DATA_SCAN_LAST_ROW}"
    vals = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=rng).execute().get("values", [])
    day_rows, last_row = [], DATA_FIRST_ROW - 1
    for i, row in enumerate(vals):
        r = DATA_FIRST_ROW + i
        b = row[0].strip() if len(row) > 0 and row[0] else ""
        if any((c or "").strip() for c in row):
            last_row = r
        if b.isdigit():
            day_rows.append((r, int(b)))
    return day_rows, last_row


def find_insert_row(day_rows, last_row, day):
    same = [r for r, d in day_rows if d == day]
    later = [r for r, d in day_rows if d > day]
    if same:
        return (min(later) if later else last_row + 1), False, (not later)
    if later:
        return min(later), True, False
    return last_row + 1, True, True


def _values(txn, write_day):
    return [[(txn["day"] if write_day else ""), txn["card"],
             classify_item(txn["detail"]), txn["detail"], txn["amount"]]]


def insert_transaction(sheets, tab_name, sheet_id, txn):
    day_rows, last_row = read_days(sheets, tab_name)
    row, write_day, is_append = find_insert_row(day_rows, last_row, txn["day"])
    if not is_append:
        reqs = [{"insertRange": {
            "range": {"sheetId": sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
                      "startColumnIndex": BF_START, "endColumnIndex": BF_END},
            "shiftDimension": "ROWS"}}]
        if row - 1 >= DATA_FIRST_ROW:
            for ptype in ("PASTE_FORMAT", "PASTE_DATA_VALIDATION"):
                reqs.append({"copyPaste": {
                    "source": {"sheetId": sheet_id, "startRowIndex": row - 2, "endRowIndex": row - 1,
                               "startColumnIndex": BF_START, "endColumnIndex": BF_END},
                    "destination": {"sheetId": sheet_id, "startRowIndex": row - 1, "endRowIndex": row,
                                    "startColumnIndex": BF_START, "endColumnIndex": BF_END},
                    "pasteType": ptype}})
        sheets.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body={"requests": reqs}).execute()
    sheets.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID, range=f"'{tab_name}'!{COL_DATE}{row}:{COL_AMOUNT}{row}",
        valueInputOption="USER_ENTERED", body={"values": _values(txn, write_day)}).execute()
    return row


def cancel_transaction(sheets, tab_name, sheet_id, txn):
    rng = f"'{tab_name}'!{COL_DATE}{DATA_FIRST_ROW}:{COL_AMOUNT}{DATA_SCAN_LAST_ROW}"
    vals = sheets.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=rng).execute().get("values", [])
    target = None
    for i, r in enumerate(vals):
        card = r[1].strip() if len(r) > 1 and r[1] else ""
        detail = r[3].strip() if len(r) > 3 and r[3] else ""
        amt = r[4].replace(",", "").strip() if len(r) > 4 and r[4] else ""
        if card == txn["card"] and detail == txn["detail"] and amt == str(txn["amount"]):
            target = DATA_FIRST_ROW + i
    if target is None:
        return None
    sheets.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body={"requests": [{
        "deleteRange": {"range": {"sheetId": sheet_id, "startRowIndex": target - 1, "endRowIndex": target,
                                  "startColumnIndex": BF_START, "endColumnIndex": BF_END},
                        "shiftDimension": "ROWS"}}]}).execute()
    return target


def month_key(month, today):
    y = today.year - 1 if (today.month == 1 and month == 12) else today.year
    return f"{y}-{month:02d}"


# ───────────────────────── 여기만 실제 작업 ─────────────────────────
def do_work(cfg, args, progress):
    token_path = getattr(args, "token", None) or str(HERE / "token.json")
    progress("Gmail·시트 인증")
    gmail, sheets = get_services(token_path)
    label_id = ensure_label(gmail)

    progress("승인문자 메일 확인")
    msgs = fetch_messages(gmail)
    parsed = [(m["id"], parse_sms(get_body_text(gmail, m["id"]), dt.date.today())) for m in msgs]
    parsed.sort(key=lambda p: {"approve": 0, "cancel": 1}.get(p[1]["kind"], 2) if p[1] else 2)

    today = dt.date.today()
    added = removed = skipped = 0
    lines, sheet_ids = [], {}

    def mark_done(mid):
        gmail.users().messages().modify(
            userId="me", id=mid, body={"addLabelIds": [label_id]}).execute()

    for mid, txn in parsed:
        if not txn:
            skipped += 1
            # 파싱 못 한 메일도 라벨 — 다음 실행(과 Worker 의 1분 감시)이 같은 메일을 다시 집지 않게
            if not args.dry_run:
                mark_done(mid)
            continue
        tab = MONTH_TAB.get(month_key(txn["month"], today))
        if not tab:
            lines.append(f"[대기] 월 탭 없음 {month_key(txn['month'], today)}")
            continue                      # 라벨 없이 둔다 — 탭이 생기면 처리
        if args.dry_run:
            lines.append(f"[예정:{txn['kind']}] {txn['month']}/{txn['day']} "
                         f"{txn['detail']} {txn['amount']:,}원 ({txn['card']})")
            if txn["kind"] == "cancel":
                removed += 1
            else:
                added += 1
            continue
        if tab not in sheet_ids:
            sheet_ids[tab] = get_sheet_id(sheets, tab)
        sid = sheet_ids[tab]
        if txn["kind"] == "cancel":
            row = cancel_transaction(sheets, tab, sid, txn)
            if row:
                removed += 1
                lines.append(f"[취소삭제] {tab} {txn['detail']} {txn['amount']:,}원")
        else:
            insert_transaction(sheets, tab, sid, txn)
            added += 1
            lines.append(f"[추가] {tab} {txn['month']}/{txn['day']} "
                         f"{txn['detail']} {txn['amount']:,}원 ({classify_item(txn['detail'])})")
        mark_done(mid)
        progress(f"기록 {added + removed}건")

    collect_txt = f"메일 {len(msgs)}건 확인, 결제 {added + removed}건"
    sheet_txt = f"추가 {added} · 취소 {removed} · 건너뜀 {skipped}"
    return {
        "counts": {"new": added, "replaced": removed, "skip": skipped, "failed": 0},
        "lines": lines,
        "tasks": {"collect": (True, collect_txt), "sheet": (True, sheet_txt)},
    }


# ───────────────────────── 아래는 템플릿 그대로 ─────────────────────────
def parse_args(argv):
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"))
    p.add_argument("--token", default=None, help="로컬 시험용 token.json 경로")
    return p.parse_args(argv)


def load_config(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_summary(counts, elapsed):
    names = {"new": "신규", "replaced": "취소", "failed": "실패", "skip": "건너뜀"}
    parts = [f"{names[k]} {v}건" for k, v in counts.items() if k in names]
    parts.append(f"{elapsed/60:.1f}분" if elapsed >= 60 else f"{int(elapsed)}초")
    return ", ".join(parts)


def build_tasks(cfg, results):
    out = []
    for tid in cfg.get("tasks") or []:
        ok, text = results.get(tid, (True, ""))
        out.append({"id": tid, "status": "done" if ok else "error", "summary": text})
    return out


def _report(cfg, **kw):
    repo = (cfg.get("office_repo") or "").strip()
    if repo and report_status:
        report_status(repo, automation_id=AUTOMATION_ID, name=AUTOMATION_NAME, dept=DEPT,
                      next_run=cfg.get("next_run", ""), link=cfg.get("result_link", ""),
                      workspace=cfg.get("office_workspace", "home"), **kw)


def run(argv, work=None):
    args = parse_args(argv)
    cfg = load_config(args.config)
    started_at = dt.datetime.now(KST).isoformat(timespec="seconds")
    started = time.monotonic()
    work = work or do_work
    progress = lambda m: print(f"  · {m}")  # noqa: E731
    try:
        result = work(cfg, args, progress)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        summary = to_korean(exc)
        detail = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(f"{summary} ({detail})", file=sys.stderr)
        if not args.dry_run:
            _report(cfg, ok=False, summary=summary, log_lines=[summary, detail],
                    started_at=started_at, duration_sec=int(time.monotonic() - started))
        return 1
    counts = dict(result.get("counts") or {})
    lines = list(result.get("lines") or [])
    tasks = dict(result.get("tasks") or {})
    ok = counts.get("failed", 0) == 0 and all(v[0] for v in tasks.values())
    summary = build_summary(counts, time.monotonic() - started)
    print(summary)
    if not args.dry_run:
        _report(cfg, ok=ok, summary=summary, counts=counts, log_lines=[summary] + lines[:4],
                tasks=build_tasks(cfg, tasks), started_at=started_at,
                duration_sec=int(time.monotonic() - started))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
