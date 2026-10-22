"""지방의회 회의록 자동화.

사용:
  python run_lcouncil.py                       # 실제 실행 (끝나면 상태 파일 커밋·push)
  python run_lcouncil.py --dry-run             # 상태 파일을 쓰지 않는 시험 실행
  옵션: --config 경로 (기본: 이 파일 옆 config.actions.yaml)

채울 곳은 do_work() 하나다. 나머지(설정 읽기, 오류 → 한국어, 상태 보고)는 그대로 둔다.
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# AI 오피스 공통 모듈 (automations/common): 오류 문구, 상태 보고
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from errors import to_korean  # noqa: E402
from lcouncil_sites import Http, build_site  # noqa: E402
from lcouncil_store import DriveStore, LocalStore  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:  # 보고 모듈이 없으면 보고 없이 동작
    report_status = None

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "lcouncil"
AUTOMATION_NAME = "지방의회 회의록"
DEPT = "research"
HERE = Path(__file__).resolve().parent


# ───────────────────────── 여기만 채운다 ─────────────────────────

def load_councils(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("councils") or []


def build_store(cfg: dict, args: argparse.Namespace, council: dict):
    if args.local:
        return LocalStore(args.local, council["name"])
    from google_drive import DriveClient  # noqa: E402  (automations/common)
    return DriveStore(DriveClient(), cfg["drive_folder_id"], council["name"])


def collect_council(council: dict, site, store, limit: int, dry_run: bool, progress) -> dict:
    """의회 하나. 최근 대수·회기부터 훑어 manifest 에 없는 회의록을 limit 건까지 받는다."""
    c = {"new": 0, "replaced": 0, "skip": 0, "failed": 0, "seen": 0}
    lines: list[str] = []
    done = 0
    for th in site.terms():
        for doc in site.iter_docs(th):
            c["seen"] += 1
            kind = store.needs_fetch(doc)
            if kind is None:
                c["skip"] += 1
                continue
            if dry_run:
                print(f"[받을 예정] {council['name']} 제{doc.th}대 {doc.title} {doc.date}{' (임시)' if doc.temp else ''}")
                c[kind] += 1
            else:
                try:
                    text = site.fetch_text(doc)
                    if len(text) < 200:
                        raise RuntimeError(f"본문이 너무 짧음({len(text)}자)")
                    path, size = store.save_text(doc, text)
                    store.record(doc, path, size)
                    c[kind] += 1
                    lines.append(f"[{'교체' if kind == 'replaced' else '신규'}] {council['name']} {path}")
                except Exception as exc:  # noqa: BLE001 - 한 건 실패로 전체를 멈추지 않는다
                    c["failed"] += 1
                    lines.append(f"[실패] {council['name']} {doc.title}: {str(exc)[:80]}")
                    print(lines[-1], file=sys.stderr)
            done += 1
            if not dry_run and done % 25 == 0:
                store.save_manifest()
            if done >= limit:
                progress(f"{council['name']}: 이번 실행 한도 {limit}건에 닿아 다음 실행에 이어서")
                if not dry_run:
                    store.save_manifest()
                return {"counts": c, "lines": lines}
    if not dry_run:
        store.save_manifest()
    return {"counts": c, "lines": lines}


def do_work(cfg: dict, args: argparse.Namespace, progress) -> dict:
    """councils.yaml 의 의회를 차례로 훑는다. 어댑터(template)가 없는 의회는 건너뛴다.

    args.dry_run 이면 받을 목록만 찍고 저장하지 않는다(--local 폴더가 있으면 manifest 는 거기서 읽는다).
    """
    councils = load_councils(args.councils)
    if args.council and args.council != "all":
        councils = [c for c in councils if c["id"] == args.council]
        if not councils:
            raise RuntimeError(f"모르는 의회 id: {args.council}")
    http = Http(delay=float(cfg.get("request_delay", 1.5)), retries=int(cfg.get("retries", 3)),
                timeout=int(cfg.get("timeout", 60)))
    limit = args.limit or int(cfg.get("per_run_limit", 300))

    total = {"new": 0, "replaced": 0, "failed": 0, "skip": 0, "seen": 0}
    lines: list[str] = []
    ready = errors = 0
    total_saved = 0
    for council in councils:
        site = build_site(council, http)
        if site is None:
            progress(f"{council['name']}: 어댑터 없음(준비 중), 건너뜀")
            continue
        ready += 1
        progress(f"{council['name']} 시작")
        try:
            store = build_store(cfg, args, council)
            r = collect_council(council, site, store, limit, args.dry_run, progress)
            total_saved += store.total_ok()
        except Exception as exc:  # noqa: BLE001 - 의회 하나가 막혀도 나머지는 계속
            errors += 1
            lines.append(f"[실패] {council['name']}: {to_korean(exc)} ({str(exc)[:100]})")
            print(lines[-1], file=sys.stderr)
            traceback.print_exc()
            continue
        for k in total:
            total[k] += r["counts"].get(k, 0)
        lines += r["lines"]
        progress(f"{council['name']}: 신규 {r['counts']['new']} 교체 {r['counts']['replaced']} "
                 f"실패 {r['counts']['failed']} 건너뜀 {r['counts']['skip']}")

    counts = {"new": total["new"], "replaced": total["replaced"], "failed": total["failed"] + errors}
    if not args.dry_run:
        counts["total"] = total_saved
    scan_ok = errors == 0
    return {
        "counts": counts,
        "lines": lines,
        "tasks": {
            "scan": (scan_ok, f"의회 {ready - errors}/{ready}곳 확인, 회의록 {total['seen']}건"),
            "fetch": (total["failed"] == 0, f"신규 {total['new']}건, 교체 {total['replaced']}건"),
        },
    }


# ───────────────────────── 아래는 그대로 ─────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="상태 파일을 쓰지 않고 시험 실행")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"), help="설정 파일 경로")
    p.add_argument("--councils", default=str(HERE / "councils.yaml"), help="의회 목록 파일")
    p.add_argument("--council", default="all", help="의회 id 하나만 (기본 all)")
    p.add_argument("--limit", type=int, default=None, help="의회당 이번 실행에 받을 최대 건수(기본 config per_run_limit)")
    p.add_argument("--local", default=None, help="드라이브 대신 이 폴더에 저장 (시험용)")
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_summary(counts: dict, elapsed_sec: float) -> str:
    """카드 부제 한 줄. counts 의 알려진 키를 한국어로 잇는다."""
    names = {"new": "신규", "replaced": "교체", "failed": "실패", "skip": "건너뜀", "sent": "전송", "updated": "갱신"}
    parts = [f"{names[k]} {v}건" for k, v in counts.items() if k in names]
    parts.append(f"{elapsed_sec / 60:.1f}분" if elapsed_sec >= 60 else f"{int(elapsed_sec)}초")
    return ", ".join(parts)


def build_tasks(cfg: dict, task_results: dict) -> list[dict]:
    """상태 JSON v2 의 tasks[]. 설정 `tasks:` 에 있는 id 만 만든다(원천은 app/workspaces/<사무실>.ts)."""
    out: list[dict] = []
    for tid in cfg.get("tasks") or []:
        ok, text = task_results.get(tid, (True, ""))
        out.append({"id": tid, "status": "done" if ok else "error", "summary": text})
    return out


def _report(cfg: dict, **kw) -> None:
    """office_repo 가 설정돼 있고 보고 모듈이 있을 때만 상태 파일을 쓰고 push 한다."""
    repo = (cfg.get("office_repo") or "").strip()
    if repo and report_status:
        report_status(repo, automation_id=AUTOMATION_ID, name=AUTOMATION_NAME, dept=DEPT,
                      next_run=cfg.get("next_run", ""), link=cfg.get("result_link", ""),
                      workspace=cfg.get("office_workspace", "assembly"), **kw)


def run(argv: list[str], work=None) -> int:
    """실행. 실패해도 상태 파일에 한국어 원인을 남긴 뒤 1 을 돌려준다. dry-run 은 보고하지 않는다."""
    args = parse_args(argv)
    cfg = load_config(args.config)
    started_at = datetime.now(KST).isoformat(timespec="seconds")
    started = time.monotonic()
    work = work or do_work
    progress = lambda m: print(f"  · {m}")  # noqa: E731

    try:
        result = work(cfg, args, progress)
    except Exception as exc:  # noqa: BLE001 - 원인을 상태 파일에 남기고 실패로 끝낸다
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
