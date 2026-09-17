"""수신함 정리 자동화 — 위원회 수신함에 쌓인 자료를 회의 폴더로 나눠 넣는다.

사용:
  python run_sort.py                  # 실제 정리 (옮기고 기록, 상태 파일 커밋·push)
  python run_sort.py --dry-run        # 옮기지 않고 어떻게 옮길지만 출력
  옵션: --config 경로 (기본: 이 파일 옆 config.actions.yaml)

plan = 무엇을 어디로 옮길지 정하기(클로드), move = 실제로 옮기고 기록 남기기.

**공개 저장소 주의**: 파일 이름·폴더 이름은 의원실 내부 자료다. 상태 파일·실행 일지에는 건수만 남기고,
자세한 내역은 드라이브의 `_정리기록.md` 에만 쓴다 (사용자 결정 2026-09-17).
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# AI 오피스 공통 모듈 (automations/common): 오류 문구, 클로드, 상태 보고
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from errors import to_korean  # noqa: E402
from llm import LLM, LLMError  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sort_drive import (  # noqa: E402
    LOG_NAME, append_log, ensure_folder, inbox_files, list_folders, move_file, read_text,
)
from sort_plan import SCHEMA, SYSTEM, build_prompt, clean_plan  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:
    report_status = None

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "sort"
AUTOMATION_NAME = "수신함 정리"
DEPT = "review"
HERE = Path(__file__).resolve().parent
SKIP_FILES = (LOG_NAME, "README.md", ".gitkeep")


def drive_service():
    """공용 구글 토큰으로 Drive 클라이언트 (DriveClient 와 같은 자격 증명)."""
    from google_drive import DriveClient

    return DriveClient().svc


def sort_one(service, rule: dict, llm: LLM, dry_run: bool, progress, rules: list[str] | None = None) -> dict:
    """위원회 하나의 수신함을 정리한다. {"files": n, "moved": n, "left": n, "new_folders": n}."""
    label = (rule.get("label") or "").strip()
    inbox_id = (rule.get("inbox_id") or "").strip()
    parent_id = (rule.get("parent_id") or "").strip()
    if not (label and inbox_id and parent_id):
        return {"files": 0, "moved": 0, "left": 0, "new_folders": 0}

    items = inbox_files(service, inbox_id, skip=SKIP_FILES)
    if not items:
        progress(f"{label} 수신함 비어 있음")
        return {"files": 0, "moved": 0, "left": 0, "new_folders": 0}

    folders = [f for f in list_folders(service, parent_id) if f.id != inbox_id]
    progress(f"{label} 수신함 {len(items)}개, 폴더 {len(folders)}개")

    texts = [(it.name, it.size // 1024, read_text(service, it)) for it in items]
    prompt = build_prompt(label, folders, texts, (rules or []) + list(rule.get("rules") or []))
    plan = llm.json(system=SYSTEM, user=prompt, schema=SCHEMA)  # dict 또는 list
    moves = clean_plan(plan, [it.name for it in items], [f.name for f in folders],
                       allow_new=bool(rule.get("allow_new_folders", True)))
    progress(f"{label} 옮길 것 {len(moves)}개, 둘 것 {len(items) - len(moves)}개")

    if dry_run:
        for mv in moves:
            print(f"  · {mv['file'][:45]} → {mv['folder']}{' (새 폴더)' if mv['new'] else ''} · {mv['reason']}")
        return {"files": len(items), "moved": 0, "left": len(items), "new_folders": 0}

    by_name = {it.name: it for it in items}
    done: list[str] = []
    new_folders = 0
    for mv in moves:
        item = by_name[mv["file"]]
        folder_id = ensure_folder(service, parent_id, mv["folder"])
        if mv["new"]:
            new_folders += 1
        move_file(service, item.id, folder_id, inbox_id)
        done.append(f"`{mv['file']}` → **{mv['folder']}**{' (새 폴더)' if mv['new'] else ''} — {mv['reason']}")
    left = [it.name for it in items if it.name not in {m["file"] for m in moves}]
    if left:
        done += [f"`{name}` → 수신함에 그대로 (어디에 둘지 확신 없음)" for name in left]
    if done:
        append_log(service, inbox_id, done)
    return {"files": len(items), "moved": len(moves), "left": len(left), "new_folders": new_folders}


def do_work(cfg: dict, args: argparse.Namespace, progress) -> dict:
    """위원회마다 수신함을 정리한다. 한 위원회가 실패해도 나머지는 계속한다."""
    rules = list(cfg.get("committees") or [])
    service = drive_service()
    llm = LLM(list(cfg.get("llm_providers") or ["claude_cli", "gemini"]))

    total = {"files": 0, "moved": 0, "left": 0, "new_folders": 0}
    lines: list[str] = []
    failed: list[str] = []
    for rule in rules:
        label = (rule.get("label") or "").strip()
        try:
            got = sort_one(service, rule, llm, args.dry_run, progress, list(cfg.get("rules") or []))
        except LLMError as exc:
            progress(f"{label} 정리 실패 — {str(exc)[:60]}")
            failed.append(label)
            continue
        for k, v in got.items():
            total[k] += v
        if got["files"]:
            lines.append(f"{label} {got['moved']}건 정리, {got['left']}건 보류")   # 파일 이름은 넣지 않는다

    if failed:
        raise LLMError(f"수신함 정리 실패: {', '.join(failed)}")

    tasks = {
        "plan": (True, f"파일 {total['files']}개 검토"),
        "move": (True, f"{total['moved']}개 정리, {total['left']}개 보류"),
    }
    counts = {"moved": total["moved"], "skip": total["left"]}
    if total["new_folders"]:
        counts["new"] = total["new_folders"]
    return {"counts": counts, "lines": lines or ["정리할 파일 없음"], "tasks": tasks,
            "skip_report": total["files"] == 0}


# ───────────────────────── 아래는 템플릿 그대로 ─────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="옮기지 않고 계획만 출력")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"), help="설정 파일 경로")
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_summary(counts: dict, elapsed_sec: float) -> str:
    names = {"moved": "정리", "skip": "보류", "new": "새 폴더", "failed": "실패"}
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
