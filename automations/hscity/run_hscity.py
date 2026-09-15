"""화성시청 동탄(화성시을) 공고 수집 자동화.

사용:
  python run_hscity.py                       # 실제 실행 (Drive 업로드 + 텔레그램 알림 + 상태 커밋)
  python run_hscity.py --dry-run             # 저장·전송 없이 시험 실행(소량만 훑음)
  옵션: --config 경로 (기본: 이 파일 옆 config.actions.yaml)

채운 곳은 do_work() 하나. 나머지 뼈대(설정 읽기, 오류→한국어, 상태 보고)는 템플릿 그대로.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

import yaml

# 공통 모듈(automations/common): 오류 문구, 상태 보고
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from errors import to_korean  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:
    report_status = None

# 이 자동화 전용 라이브러리(automations/hscity/hslib)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from hslib import fetcher, state as state_mod, filter as filt_mod, detailer  # noqa: E402
from hslib.adapters import get_adapter  # noqa: E402
from hslib.collector import collect_new  # noqa: E402
from hslib.download import build_download_url  # noqa: E402
from hslib.extract import extract_text  # noqa: E402
from hslib.archive import sanitize  # noqa: E402
from hslib.summarize import basic_summary  # noqa: E402
from hslib.store import DriveStore, LocalStore  # noqa: E402
from hslib.telegram import send_message, telegram_env, format_message  # noqa: E402

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "hscity"
AUTOMATION_NAME = "화성시 공고 수집"
DEPT = "review"
HERE = Path(__file__).resolve().parent

_EXT_MIME = {".hwpx": "application/octet-stream", ".hwp": "application/octet-stream",
             ".pdf": "application/pdf", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             ".xls": "application/vnd.ms-excel", ".zip": "application/zip"}


def _year(date: str) -> str:
    m = re.match(r"(\d{4})", date or "")
    return m.group(1) if m else "9999"


def _post_dir(board_name: str, date: str, post_id: str, keyword: str, title: str) -> PurePosixPath:
    folder = sanitize("_".join(p for p in [date or "", post_id, keyword, title] if p))
    return PurePosixPath(_year(date)) / board_name / folder


def _first_keyword(text: str, includes: list[str]) -> str:
    for k in includes:
        if k in text:
            return k
    return ""


def _wonmun_md(meta: dict) -> str:
    return (
        f"# {meta.get('title', '')}\n\n"
        f"- 고시공고번호: {meta.get('reg_no', '')}\n"
        f"- 게재일자: {meta.get('date', '')}\n"
        f"- 담당부서: {meta.get('dept', '')}\n"
        f"- 담당자/연락처: {meta.get('contact', '')}\n"
        f"- 원문 링크: {meta.get('url', '')}\n\n"
        f"## 본문\n\n{meta.get('body', '')}\n"
    )


def _summary_md(post: dict) -> str:
    eul = "⭐ 화성시을 확실" if post.get("is_star") else ("시 전역" if post.get("is_citywide") else "동탄 관련")
    lines = [f"# {post['title']}", "", (post.get("summary") or "").strip(), "",
             f"- 게시판: {post['board_name']}", f"- 담당부서: {post.get('dept', '')}",
             f"- 게재일자: {post.get('date', '')}", f"- 화성시을: {eul}",
             f"- 원문: {post['url']}", "", "## 첨부"]
    for a in post.get("attachments", []):
        mark = "" if a.get("extract_ok", True) else " (추출 실패)"
        lines.append(f"- {a.get('user_file_nm', '')}{mark}")
    return "\n".join(lines) + "\n"


def _fetch_bytes(session, cfg, att) -> bytes:
    if att.get("kind") == "nd":
        href = att.get("href", "")
        url = cfg["base_url"] + href if href.startswith("/") else href
    else:
        url = build_download_url(cfg["download_base"], att["user_file_nm"], att["sys_file_nm"], att["file_path"])
    r = session.get(url, timeout=60)
    r.raise_for_status()
    return r.content


def _detail_with_retry(session, cfg, board, detail_id, tries=3):
    last = None
    for _ in range(tries):
        try:
            return detailer.fetch_detail(session, cfg, board, detail_id)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.0)
    raise last


def _make_store(cfg: dict, dry_run: bool):
    if dry_run:
        return LocalStore(Path(tempfile.mkdtemp(prefix="hscity_dry_")))
    from google_drive import DriveClient  # common/ (sys.path 에 추가됨)
    client = DriveClient()
    return DriveStore(client, cfg["drive_parent_id"], cfg.get("drive_folder_name", "공고수집"))


# ───────────────────────── 여기만 채운다 ─────────────────────────

def do_work(cfg: dict, args: argparse.Namespace, progress) -> dict:
    boards = cfg["boards"]
    base = cfg["base_url"]
    filt = cfg["filter"]
    includes = filt["include_keywords"]
    notify_exclude = cfg.get("notify_exclude", [])
    since = cfg.get("bootstrap_since", "2000-01-01")

    session = fetcher.make_session()
    store = _make_store(cfg, args.dry_run)
    manifest = store.load_manifest()          # {board_id: 마지막 처리 글번호}
    bootstrap = not manifest

    if args.dry_run:
        max_pages = int(cfg.get("dry_max_pages", 1))
    elif bootstrap:
        max_pages = int(cfg.get("bootstrap_max_pages", 20))
    else:
        max_pages = int(cfg.get("max_pages_per_board", 5))

    def fetch_list(url):
        return fetcher.get_with_retry(session, url).text

    new_posts: list[dict] = []
    lines: list[str] = []
    failed = 0

    for board in boards:
        adapter = get_adapter(board["adapter"])
        try:
            rows = collect_new(board, adapter, manifest, base, fetch_list, max_pages)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            lines.append(f"[실패] {board['name']} 목록: {type(exc).__name__}")
            progress(f"{board['name']} 목록 실패: {exc}")
            continue

        progress(f"{board['name']}: 신규 후보 {len(rows)}건")
        max_id = manifest.get(board["id"])
        for row in rows:
            if max_id is None or state_mod.is_new({board["id"]: max_id}, board["id"], row["post_id"]):
                max_id = row["post_id"]
            if bootstrap and (row.get("date") or "") < since:
                continue
            detail_id = row.get("detail_key", row["post_id"])
            try:
                d, url = _detail_with_retry(session, cfg, board, detail_id)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                lines.append(f"[실패] {board['name']} 상세 {row['post_id']}: {type(exc).__name__}")
                continue

            title = d.get("title") or row.get("title", "")
            body = d.get("body", "")
            m = filt_mod.match(title, body, filt)
            if not m.included:
                continue

            date = d.get("date") or row.get("date", "")
            post = {
                "board_id": board["id"], "board_name": board["name"], "post_id": row["post_id"],
                "title": title, "dept": d.get("dept", ""), "date": date, "reg_no": d.get("reg_no", ""),
                "url": url, "body": body, "is_star": m.is_star, "is_citywide": m.is_citywide,
                "summary": basic_summary(body), "attachments": [],
            }

            if not args.dry_run:
                try:
                    rel = _post_dir(board["name"], date, row["post_id"],
                                    _first_keyword(f"{title} {body}", includes), title)
                    store.write_text(rel / "원문.md", _wonmun_md({**d, "url": url, "title": title, "date": date}))
                    for a in d.get("attachments", []):
                        name = sanitize(a.get("user_file_nm") or "attachment", maxlen=120)
                        try:
                            data = _fetch_bytes(session, cfg, a)
                            ext = os.path.splitext(name)[1].lower()
                            ok, text = False, ""
                            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tf:
                                tf.write(data)
                                tmp = tf.name
                            try:
                                ok, text = extract_text(tmp)
                            finally:
                                os.unlink(tmp)
                            store.write_bytes(rel / "첨부" / name, data, _EXT_MIME.get(ext, "application/octet-stream"))
                            post["attachments"].append({**a, "extract_ok": ok, "extracted_text": text})
                        except Exception as exc:  # noqa: BLE001
                            lines.append(f"[첨부실패] {name}: {type(exc).__name__}")
                            post["attachments"].append({**a, "extract_ok": False, "extracted_text": ""})
                    store.write_text(rel / "요약.md", _summary_md(post))
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    lines.append(f"[실패] 저장 {board['name']} {row['post_id']}: {type(exc).__name__}")
                    continue

            new_posts.append(post)
            star = "⭐" if m.is_star else ""
            lines.append(f"[신규]{star} [{board['name']}] {title[:40]}")

        if max_id is not None:
            manifest[board["id"]] = max_id

    if not args.dry_run:
        store.save_manifest(manifest)

    # 텔레그램 알림 — 행정 루틴(공시송달·반송 등)은 제외, 파일은 이미 저장됨
    def _noise(p):
        return any(k in p["title"] for k in notify_exclude)

    alertable = [p for p in new_posts if not _noise(p)]
    sent = 0
    if not args.dry_run and (alertable or bootstrap):
        token, chat = telegram_env()
        if bootstrap:
            send_message(token, chat,
                         f"📦 화성시 동탄(화성시을) 공고 초기 수집 {len(new_posts)}건 완료. "
                         f"요약은 Drive 폴더의 요약.md 참고.", retries=cfg.get("retries", 3))
            sent = 0
        else:
            for p in alertable:
                send_message(token, chat, format_message(p), retries=cfg.get("retries", 3))
                sent += 1

    counts = {"new": len(new_posts), "sent": sent, "failed": failed}
    n_att = sum(len(p["attachments"]) for p in new_posts)
    collect_line = f"신규 {len(new_posts)}건" + (f", 첨부 {n_att}건" if n_att else "")
    notify_line = (f"{sent}건 발송" if not bootstrap else f"초기 {len(new_posts)}건 요약 1건") + \
                  (f", 무음 {len(new_posts) - len(alertable)}건" if new_posts else "")
    tasks = {
        "collect": (failed == 0, collect_line),
        "notify": (True, notify_line),
    }
    return {"counts": counts, "lines": lines, "tasks": tasks}


# ───────────────────────── 아래는 템플릿 그대로 ─────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="저장·전송 없이 시험 실행")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"), help="설정 파일 경로")
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_summary(counts: dict, elapsed_sec: float) -> str:
    names = {"new": "신규", "replaced": "교체", "failed": "실패", "skip": "건너뜀", "sent": "전송", "updated": "갱신"}
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
    ok = counts.get("failed", 0) == 0 and all(v[0] for v in task_results.values())
    summary = build_summary(counts, time.monotonic() - started)
    print(summary)
    if not args.dry_run:
        _report(cfg, ok=ok, summary=summary, counts=counts, log_lines=[summary] + lines[:4],
                tasks=build_tasks(cfg, task_results), started_at=started_at,
                duration_sec=int(time.monotonic() - started))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
