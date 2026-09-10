"""기사 수집 자동화 — 구글 뉴스 RSS 로 의원·위원회 기사를 모아 드라이브에 하루치로 정리한다.

사용:
  python run_news.py                       # 실제 실행 (드라이브 저장 + 상태 파일 커밋·push)
  python run_news.py --dry-run             # 저장·보고 없이 기사만 받아 요약 출력
  옵션: --config 경로 (기본: 이 파일 옆 config.actions.yaml)

collect = 기사 모으기(RSS 조회·신규 판정), digest = 요약 정리(중복 합치기·묶음별 정리·드라이브 저장).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

# AI 오피스 공통 모듈 (automations/common): 오류 문구, 상태 보고, 드라이브
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from errors import MissingGoogleToken, to_korean  # noqa: E402
import news_digest as digest_mod  # noqa: E402
from google_news import GoogleNews  # noqa: E402
from news_store import DriveStore, day_path  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:  # 보고 모듈이 없으면 보고 없이 동작
    report_status = None

KST = timezone(timedelta(hours=9))
AUTOMATION_ID = "news"
AUTOMATION_NAME = "기사 수집"
DEPT = "brand"
HERE = Path(__file__).resolve().parent


# ───────────────────────── 여기만 채운다 ─────────────────────────

def open_store(cfg: dict):
    """드라이브 저장소를 연다. 폴더가 없으면 만든다."""
    from google_drive import DriveClient

    if not (os.environ.get("GOOGLE_REFRESH_TOKEN") or "").strip():
        raise MissingGoogleToken("GOOGLE_REFRESH_TOKEN 이 없어 드라이브에 저장할 수 없습니다")
    parent_id = (cfg.get("drive_parent_id") or "").strip()
    if not parent_id:
        raise RuntimeError("설정에 drive_parent_id 가 없습니다")
    return DriveStore(DriveClient(), parent_id, cfg.get("drive_folder_name") or "12. 언론모니터링")


def collect(cfg: dict, progress) -> tuple[list, list[str]]:
    """검색어마다 RSS 를 받아 기사 목록을 만든다. 한 검색어가 실패하면 그 줄만 남기고 계속한다."""
    news = GoogleNews(delay=float(cfg.get("request_delay", 1.0)),
                      retries=int(cfg.get("retries", 3)),
                      timeout=int(cfg.get("timeout", 30)))
    days = int(cfg.get("search_days", 1))
    articles, failed = [], []
    for entry in cfg.get("queries") or []:
        q, group = entry.get("q", ""), entry.get("group", "")
        if not q:
            continue
        try:
            found = news.fetch(q, group=group, days=days)
        except RuntimeError as exc:
            failed.append(f"[실패] {q}: {exc}")
            progress(f"{q} — 실패")
            continue
        articles += found
        progress(f"{q} — {len(found)}건")
    if failed and not articles:
        raise RuntimeError(failed[0])   # 전부 실패하면 자동화를 실패로 끝낸다
    return articles, failed


def do_work(cfg: dict, args: argparse.Namespace, progress) -> dict:
    """기사를 모아(collect) 중복을 합치고 묶음별로 정리해 드라이브에 쓴다(digest)."""
    now = datetime.now(KST)
    day = now.date().isoformat()
    groups = list(dict.fromkeys(e.get("group", "") for e in (cfg.get("queries") or []) if e.get("group")))

    progress("기사 모으는 중")
    articles, failed = collect(cfg, progress)
    items = digest_mod.dedupe(articles)
    progress(f"기사 {len(articles)}건 → 중복 합쳐 {len(items)}건")

    store = None if args.dry_run else open_store(cfg)
    manifest = store.load_manifest() if store else {}
    fresh = digest_mod.merge_manifest(manifest, items, now=now)
    dropped = digest_mod.prune_manifest(manifest, keep_days=int(cfg.get("manifest_days", 60)), now=now)

    rows = digest_mod.entries_for_day(manifest, day)
    page = digest_mod.render_day(day, rows, groups, updated_at=now.strftime("%Y-%m-%d %H:%M"))

    if store:
        store.write_text(day_path(day), page)
        store.save_manifest(manifest)
        progress(f"드라이브 저장 완료 ({day}.md)")
    else:
        print()
        print("----- 미리보기 (저장하지 않음) -----")
        print(page)
        print("-----------------------------------")

    top = ", ".join(f"{m} {n}건" for m, n in digest_mod.media_counts(rows)[:3])
    lines = [f"[신규] {a['title']} — {', '.join(a['sources'])}" for a in fresh[:6]] + failed
    if dropped:
        lines.append(f"[정리] 오래된 기록 {dropped}건 삭제")
    return {
        "counts": {"new": len(fresh), "failed": len(failed), "total": len(manifest)},
        "lines": lines,
        "tasks": {
            "collect": (not failed, f"검색어 {len(cfg.get('queries') or [])}개에서 {len(articles)}건"
                                    + (f", 실패 {len(failed)}개" if failed else "")),
            "digest": (True, f"오늘 {len(rows)}건 (신규 {len(fresh)}건)" + (f" · {top}" if top else "")),
        },
    }


# ───────────────────────── 아래는 그대로 ─────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=AUTOMATION_NAME)
    p.add_argument("--dry-run", action="store_true", help="상태 파일을 쓰지 않고 시험 실행")
    p.add_argument("--config", default=str(HERE / "config.actions.yaml"), help="설정 파일 경로")
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
