"""의사일정 자동화 — 회의 폴더의 의사일정 파일을 읽어 530호 캘린더에 회의 일정을 넣는다.

사용:
  python run_agenda.py                  # 실제 실행 (캘린더에 넣고, 상태 파일 커밋·push)
  python run_agenda.py --dry-run        # 넣지 않고 무엇을 넣을지만 출력
  옵션: --config 경로 (기본: 이 파일 옆 config.actions.yaml)

read = 오늘 이후 회의 폴더에서 의사일정 찾아 읽기, sync = 캘린더에 넣기(같은 회의는 한 번만).
위원회 폴더 위치는 수신함 정리 설정(automations/sort/config.actions.yaml 의 committees)을 그대로 쓴다.

**공개 저장소 주의**: 상태 파일·실행 일지에는 건수만 남긴다. 회의 이름·시각은 캘린더에만 쓴다.
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from errors import to_korean  # noqa: E402
sys.path.insert(0, str(HERE.parent / "sort"))
from sort_drive import FOLDER_MIME, Item, read_text  # noqa: E402
sys.path.insert(0, str(HERE.parent / "weekend"))
from weekend_calendar import calendar_service, fetch_events  # noqa: E402
sys.path.insert(0, str(HERE))
from agenda_parse import build_event, decide, end_of, folder_date, is_sub, parse_header  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:
    report_status = None

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "agenda"
AUTOMATION_NAME = "의사일정"
DEPT = "partner"
SORT_CONFIG = HERE.parent / "sort" / "config.actions.yaml"


def agenda_files(drive, parent_id: str, today: str) -> list[tuple[str, str, Item]]:
    """오늘 이후 회의 폴더(YYYYMMDD_…) 안의 의사일정 파일 — (폴더 날짜, 폴더 id, 파일),
    오래 고친 것부터(나중 것이 이긴다). 폴더 날짜는 본문에 연도가 없을 때 쓴다."""
    folders = drive.files().list(
        q=f"'{parent_id}' in parents and mimeType = '{FOLDER_MIME}' and trashed = false",
        fields="files(id,name)", pageSize=1000).execute().get("files", [])
    out: list[tuple[str, str, Item]] = []
    for f in folders:
        fdate = folder_date(f["name"]) or ""
        if fdate < today:
            continue
        files = drive.files().list(
            q=f"'{f['id']}' in parents and name contains '의사일정' and trashed = false and mimeType != '{FOLDER_MIME}'",
            fields="files(id,name,size)", pageSize=20, orderBy="modifiedTime").execute().get("files", [])
        out += [(fdate, f["id"], Item(x["id"], x["name"], int(x.get("size") or 0))) for x in files]
    return out


def do_work(cfg: dict, args: argparse.Namespace, progress) -> dict:
    from google_drive import DriveClient
    from googleapiclient.errors import HttpError

    committees = (yaml.safe_load(SORT_CONFIG.read_text(encoding="utf-8")) or {}).get("committees") or []
    calendar_id = cfg["calendar_id"]
    end_time = str(cfg.get("end_time") or "18:00")
    same_as = cfg.get("same_as") or {}
    drive = DriveClient().svc
    cal = calendar_service()
    today = datetime.now(KST).strftime("%Y%m%d")

    n = {"files": 0, "unread": 0, "sub": 0, "add": 0, "move": 0, "same": 0, "manual": 0, "deleted": 0}
    for c in committees:
        label = (c.get("label") or "").strip()
        for fdate, folder_id, item in agenda_files(drive, (c.get("parent_id") or "").strip(), today):
            n["files"] += 1
            m = parse_header(read_text(drive, item, max_chars=300), fdate)
            if not m:
                n["unread"] += 1
                continue
            if is_sub(m):
                n["sub"] += 1
                continue
            day = m.start.date()
            what = decide(label, m, fetch_events(cal, calendar_id, (day,)), tuple(same_as.get(label) or ()))
            event = build_event(label, m, end_time,
                                f"의사일정에서 자동으로 넣은 일정입니다.\n회의 폴더: https://drive.google.com/drive/folders/{folder_id}")
            if args.dry_run:
                print(f"  · [{what}] {event['summary']} {m.start:%m/%d %H:%M}~{end_of(m, end_time):%H:%M}")
            elif what == "add":
                try:
                    cal.events().insert(calendarId=calendar_id, body=event).execute()
                except HttpError as exc:
                    if exc.resp.status != 409:
                        raise
                    what = "deleted"      # 사람이 지운 일정 — 다시 넣지 않는다
            elif what == "move":          # 회의 시각이 바뀌었다 — 시각만 고친다
                cal.events().patch(calendarId=calendar_id, eventId=event["id"],
                                   body={"start": event["start"], "end": event["end"]}).execute()
            n[what] += 1
    progress(f"의사일정 {n['files']}개 — 새로 {n['add']}, 시각 고침 {n['move']}, 그대로 {n['same'] + n['manual'] + n['deleted']}")

    skipped = n["unread"] + n["sub"]
    tasks = {
        "read": (True, f"의사일정 {n['files']}개 읽음" + (f", {n['unread']}개는 못 읽음" if n["unread"] else "")),
        "sync": (True, f"새로 {n['add']}건, 시각 고침 {n['move']}건, 이미 있음 {n['same'] + n['manual']}건"),
    }
    counts = {"new": n["add"], "moved": n["move"], "skip": skipped}
    lines = [f"새 일정 {n['add']}건, 시각 고침 {n['move']}건"]   # 회의 이름·시각은 넣지 않는다
    if n["unread"]:
        lines.append(f"첫 줄을 못 읽은 의사일정 {n['unread']}개 — 손으로 넣어 주세요")
    # 바뀐 것도 못 읽은 것도 없으면 상태 파일을 다시 쓰지 않는다(메일이 올 때마다 빈 커밋이 쌓이지 않게)
    return {"counts": counts, "lines": lines, "tasks": tasks,
            "skip_report": not (n["add"] or n["move"] or n["unread"])}


# ───────────────────────── 아래는 템플릿 그대로 ─────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="넣지 않고 계획만 출력")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"), help="설정 파일 경로")
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_summary(counts: dict, elapsed_sec: float) -> str:
    names = {"new": "새 일정", "moved": "시각 고침", "skip": "건너뜀"}
    parts = [f"{names[k]} {v}건" for k, v in counts.items() if k in names]
    parts.append(f"{elapsed_sec / 60:.1f}분" if elapsed_sec >= 60 else f"{int(elapsed_sec)}초")
    return ", ".join(parts)


def build_tasks(cfg: dict, task_results: dict) -> list[dict]:
    out: list[dict] = []
    for tid in cfg.get("tasks") or []:
        ok, text = task_results.get(tid, (True, ""))
        out.append({"id": tid, "status": "done" if ok else "error", "summary": text})
    return out


def _report(cfg: dict, **kw) -> None:
    repo = (cfg.get("office_repo") or "").strip()
    if repo and report_status:
        report_status(repo, automation_id=AUTOMATION_ID, name=AUTOMATION_NAME, dept=DEPT,
                      next_run=cfg.get("next_run", ""), link=cfg.get("result_link", ""),
                      workspace=cfg.get("office_workspace", "assembly"), **kw)


def run(argv: list[str], work=None) -> int:
    args = parse_args(argv)
    cfg = load_config(args.config)
    started_at = datetime.now(KST).isoformat(timespec="seconds")
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
    task_results = dict(result.get("tasks") or {})
    ok = all(v[0] for v in task_results.values())
    summary = build_summary(counts, time.monotonic() - started)
    print(summary)
    if not args.dry_run and not result.get("skip_report"):
        _report(cfg, ok=ok, summary=summary, counts=counts, log_lines=[summary] + lines[:4],
                tasks=build_tasks(cfg, task_results), started_at=started_at,
                duration_sec=int(time.monotonic() - started))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
