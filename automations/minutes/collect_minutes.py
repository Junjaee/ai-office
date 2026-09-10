"""국회회의록 PDF 수집기.

사용:
  python collect_minutes.py --daily              # 최근 회기만 확인 (기본)
  python collect_minutes.py --backfill 22,21     # 대수 전체 수집
  옵션: --dry-run (받지 않고 목록만) --limit N (N건 받고 중단) --config 경로
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

# 이 PC의 urllib3/chardet 버전 조합 경고는 동작에 영향이 없어 숨긴다
warnings.filterwarnings("ignore", message="urllib3 .* or chardet")

from catalog import iter_entries, iter_temp_recheck, MinutesEntry
from open_api import OpenApi
from record_site import RecordSite
from store import DriveApiStore, LocalDriveStore

# AI 오피스 대시보드 보고 모듈 (automations/common). 없으면 보고 없이 동작한다.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from errors import MSG_GOOGLE, MissingGoogleToken, to_korean  # noqa: E402
try:
    from report_status import report as report_status  # noqa: E402
except ImportError:
    report_status = None

KST = timezone(timedelta(hours=9))


def build_store(cfg: dict, drive_client=None):
    """config의 storage 값에 따라 로컬 폴더 저장소 또는 Google Drive API 저장소를 만든다."""
    if (cfg.get("storage") or "local") == "drive":
        if drive_client is None:
            from google_drive import DriveClient  # noqa: E402  (automations/common)
            drive_client = DriveClient()
        return DriveApiStore(drive_client, cfg["drive_folder_id"])
    return LocalDriveStore(cfg["drive_root"])


ALL_CLASSES = [1, 2, 3, 4, 5, 6]
SITE_ONLY_CLASSES = [5, 6]          # 국정감사·국정조사는 Open API가 데이터를 주지 않는다
HERE = Path(__file__).resolve().parent


def month_prefixes(n: int, today: date | None = None) -> list[str]:
    """오늘부터 거슬러 n개월의 'YYYY-MM' 목록 (최근 순)."""
    d = today or date.today()
    out = []
    for _ in range(n):
        out.append(f"{d.year:04d}-{d.month:02d}")
        d = (d.replace(day=1) - timedelta(days=1))
    return out


def iter_daily(site, api, store: LocalDriveStore, th: int, recent: int, api_months: int, progress):
    """매일 확인 목록. Open API가 있으면 본회의·위원회는 API로, 국감·국조와 임시 재확인은 사이트로."""
    if api is None:
        yield from iter_entries(site, th, ALL_CLASSES, recent=recent, progress=progress)
        return
    for prefix in month_prefixes(api_months):
        entries = api.entries(th, prefix)
        progress(f"Open API {prefix}: 회의록 {len(entries)}건")
        yield from entries
    yield from iter_entries(site, th, SITE_ONLY_CLASSES, recent=recent, progress=progress)
    yield from iter_temp_recheck(site, th, store.pending_temp(th), progress=progress)


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="국회회의록 PDF 수집")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--daily", action="store_true", help="최근 회기만 확인 (기본)")
    mode.add_argument("--backfill", metavar="TH", help="대수 전체 수집, 예: 22 또는 22,21")
    p.add_argument("--dry-run", action="store_true", help="다운로드 없이 목록만 출력")
    p.add_argument("--limit", type=int, default=None, help="이 건수만큼 받고 중단")
    p.add_argument("--config", default=str(HERE / "config.yaml"))
    return p.parse_args(argv)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def process(entry: MinutesEntry, site, store: LocalDriveStore, dry_run: bool) -> str:
    """한 건 처리. 반환: 'new' | 'replaced' | 'skip' | 'no_pdf' | 'error'."""
    prev = store.manifest.get(str(entry.id))
    if not store.needs_download(entry):
        if prev is None and not entry.has_pdf:
            if not dry_run:
                store.record(entry, status="no_pdf", path=None, size=0)
            return "no_pdf"
        return "skip"
    kind = "replaced" if prev and prev.get("status") == "ok" else "new"
    if dry_run:
        print(f"[받을 예정] {entry.id} {entry.class_name}/{entry.committee}/{entry.sess} {entry.title}"
              f"{' (임시)' if entry.temp else ''}")
        return kind
    try:
        filename, data = site.download_pdf(entry.id)
        rel = store.relative_path(entry, filename)
        size = store.save_pdf(rel, data)
        store.record(entry, status="ok", path=rel.as_posix(), size=size)
        print(f"[{'교체' if kind == 'replaced' else '신규'}] {rel.as_posix()} ({size // 1024} KB)")
        return kind
    except Exception as exc:  # noqa: BLE001 - 한 건 실패로 전체를 멈추지 않는다
        store.record(entry, status="error", path=None, size=0)
        print(f"[실패] {entry.id} {entry.title}: {exc}", file=sys.stderr)
        return "error"


def build_tasks(cfg: dict, counts: dict) -> list[dict]:
    """상태 JSON v2의 tasks[]. 설정 `tasks:` 목록에 있는 id만 만든다(원천은 app/workspaces/assembly.ts)."""
    out: list[dict] = []
    for tid in cfg.get("tasks") or []:
        if tid == "collect":
            out.append({"id": "collect", "status": "done" if counts["error"] == 0 else "error",
                        "summary": f"신규 {counts['new']}건"})
        elif tid == "replace":
            out.append({"id": "replace", "status": "done", "summary": f"교체 {counts['replaced']}건"})
    return out


def _report(cfg: dict, **kw) -> None:
    """office_repo가 설정돼 있고 보고 모듈이 있을 때만 상태 파일을 쓰고 push 한다."""
    repo = (cfg.get("office_repo") or "").strip()
    if repo and report_status:
        report_status(repo, automation_id="minutes", name="국회회의록 수집", dept="research",
                      next_run=cfg.get("next_run", "매일 09:00"), link=cfg.get("drive_link", ""),
                      workspace=cfg.get("office_workspace", "assembly"), **kw)


def run(argv: list[str], site=None, api=None, drive_client=None) -> int:
    """수집 실행. 실패해도(예외·토큰 없음) 상태 파일에 한국어 원인을 남긴 뒤 1을 돌려준다.

    dry-run은 성공/실패 모두 보고하지 않는다(상태 파일이 화면과 어긋나지 않도록).
    """
    args = parse_args(argv)
    cfg = load_config(args.config)
    started_at = datetime.now(KST).isoformat(timespec="seconds")
    started = time.monotonic()
    counts = {"new": 0, "replaced": 0, "skip": 0, "no_pdf": 0, "error": 0}

    def fail(exc: BaseException) -> int:
        summary = to_korean(exc)
        detail = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(f"{summary} ({detail})", file=sys.stderr)
        if not args.dry_run:
            _report(cfg, ok=False, summary=summary, counts=dict(counts), log_lines=[summary, detail],
                    started_at=started_at, duration_sec=int(time.monotonic() - started), tasks=None)
        return 1

    # 드라이브 저장소인데 토큰이 없으면 DriveApiStore(=DriveClient)를 만들기 전에 끝낸다.
    # 주입된 drive_client가 있으면(테스트) 이미 인증된 것으로 본다.
    if (cfg.get("storage") or "local") == "drive" and drive_client is None \
            and not (os.environ.get("GOOGLE_REFRESH_TOKEN") or "").strip():
        return fail(MissingGoogleToken(f"{MSG_GOOGLE} (GOOGLE_REFRESH_TOKEN 환경변수가 비어 있음)"))

    try:
        return _run_body(args, cfg, site, api, drive_client, counts, started_at, started)
    except Exception as exc:  # noqa: BLE001 - 원인을 상태 파일에 남기고 실패로 끝낸다
        traceback.print_exc()
        return fail(exc)


def _run_body(args, cfg: dict, site, api, drive_client, counts: dict, started_at: str, started: float) -> int:
    site = site or RecordSite(delay=cfg["request_delay"], retries=cfg["retries"], timeout=cfg["timeout"])
    key = (cfg.get("open_api_key") or os.environ.get("OPEN_API_KEY") or "").strip()
    if api is None and key:
        api = OpenApi(key, timeout=cfg["timeout"])
    store = build_store(cfg, drive_client)
    progress = lambda m: print(f"  · {m}")  # noqa: E731

    if args.backfill:
        ths = [int(x) for x in args.backfill.split(",")]
        recent = None
        mode = f"backfill {args.backfill}"
    else:
        ths = [int(cfg["current_th"])]
        recent = int(cfg["recent_sessions"])
        mode = "daily" + (" (Open API)" if api else "")

    lines: list[str] = []
    stop = False
    for th in ths:
        if args.backfill:
            entries = iter_entries(site, th, ALL_CLASSES, recent=None, progress=progress)
        else:
            entries = iter_daily(site, api, store, th, recent, int(cfg.get("api_months", 2)), progress)
        for entry in entries:
            if store.free_gb() < float(cfg["min_free_gb"]):
                print(f"디스크 여유 {store.free_gb():.1f}GB 미만, 중단", file=sys.stderr)
                lines.append("경고: 디스크 여유 부족으로 중단")
                stop = True
                break
            result = process(entry, site, store, args.dry_run)
            counts[result] += 1
            if result in ("new", "replaced") and not args.dry_run:
                rec = store.manifest[str(entry.id)]
                lines.append(f"[{'교체' if result == 'replaced' else '신규'}] {rec['path']}")
            if result == "error":
                lines.append(f"[실패] {entry.id} {entry.title}")
            done = counts["new"] + counts["replaced"]
            if not args.dry_run and done and done % 50 == 0:
                store.save_manifest()
            if args.limit and done >= args.limit:
                stop = True
                break
        if stop:
            break

    summary = (f"신규 {counts['new']}건, 확정본 교체 {counts['replaced']}건, 실패 {counts['error']}건, "
               f"PDF없음 {counts['no_pdf']}건, 건너뜀 {counts['skip']}건, "
               f"{(time.monotonic() - started) / 60:.1f}분")
    print(summary)
    if not args.dry_run:
        store.save_manifest()
        store.log_run(mode, [summary] + lines)
        total_ok = sum(1 for v in store.manifest.values() if v.get("status") == "ok")
        _report(cfg, ok=counts["error"] == 0, summary=summary,
                counts={"new": counts["new"], "replaced": counts["replaced"],
                        "failed": counts["error"], "total": total_ok},
                log_lines=[summary] + lines[:4], tasks=build_tasks(cfg, counts),
                started_at=started_at, duration_sec=int(time.monotonic() - started))
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
