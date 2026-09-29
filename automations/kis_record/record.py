"""하루치 실시간 호가·체결 녹음 실행기.

사용:
  python record.py --codes 005930,000660 --minutes 2          # 시험(2분)
  python record.py --picks auto --until 15:35                   # 하루 녹음(작업 스케줄러가 08:50 에 부름)
  python record.py --codes ... --dry                            # 접속키만 받고 연결은 하지 않음

- 비밀값: --config(기본 ai-home/02_주식신호/config.yaml)의 kis_app_key·kis_app_secret. 값은 어디에도 찍지 않는다.
- 저장: --out(기본 %USERPROFILE%\\ai-office-data\\kis-record)/YYYY-MM-DD/run_HHMMSS/<tr_id>_<code>.csv 에 한 줄씩(5초마다 flush),
  끝나면 Parquet(zstd, 모든 열 문자열)로 바꾸고 csv 를 지운다. summary.json(로컬용 전체)·safe_summary.json(보고용 건수만)을 남긴다.
  시작할 때 앞선 실행이 남긴 csv 가 있으면 먼저 Parquet 으로 바꾼다.
- 종목: --codes 직접 지정, 또는 --picks auto(kis_pick.today_picks: 관심 종목 + 거래대금 상위) / --picks 파일(한 줄에 코드 하나).
  한도(연결당 3건)라 --mode both 는 종목 2개(첫 종목 호가+체결, 둘째 호가), --mode asp 는 3종목 호가만.
- 중복 실행 방지(잠금 파일), 녹음 중 PC 절전 방지, 09:05 까지 프레임이 없으면 휴장으로 보고 종료, 끝나면 텔레그램 한 줄(설정 있을 때만).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import ctypes
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))          # automations.common 을 쓰기 위해(저장소 루트)
import kis_client as kc  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
DEFAULT_CFG = HERE.parents[1] / "ai-home" / "02_주식신호" / "config.yaml"
# 자료 폴더: AppData 가 아니라 사용자 폴더 아래(%USERPROFILE%i-office-data). 이유(2026-09-29): Claude 앱(MSIX)이 띄운 프로세스는 AppData\Local 쓰기가
# 앱 전용 폴더(Packages\…\LocalCache\Local)로 우회돼, 작업 스케줄러 등 밖에서 띄운 프로세스와 서로 다른 폴더를 보게 된다. AI_OFFICE_DATA 로 바꿀 수 있다.
DATA_ROOT = Path(os.environ.get("AI_OFFICE_DATA", str(Path.home() / "ai-office-data")))
DEFAULT_OUT = DATA_ROOT / "kis-record"


def now_kst() -> datetime:
    return datetime.now(KST).replace(tzinfo=None)   # 로컬 비교용(naive, KST)


def log(msg: str) -> None:
    print(f"[{now_kst():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- 저장

class DayStore:
    """실행 폴더 안에 종목·TR 별 csv 를 붙여 쓰기. 파일 핸들은 열어 두고 주기적으로 flush."""

    def __init__(self, run_dir: Path):
        self.dir = run_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.files: dict[tuple[str, str], tuple] = {}
        self.last_flush = time.time()
        self.n = 0
        self.bad = open(self.dir / "bad_frames.log", "a", encoding="utf-8")

    def write(self, rows: list[dict]) -> None:
        for r in rows:
            key = (r["tr_id"], r["MKSC_SHRN_ISCD"])
            if key not in self.files:
                p = self.dir / f"{key[0]}_{key[1]}.csv"
                new = not p.exists()
                f = open(p, "a", newline="", encoding="utf-8")
                width = len([k for k in r if k not in ("recv_ms", "seq", "tr_id")])
                cols = ["recv_ms", "seq"] + kc.columns_for(key[0], width)
                w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                if new:
                    w.writeheader()
                self.files[key] = (f, w)
            self.files[key][1].writerow(r)
            self.n += 1
        if time.time() - self.last_flush > 5:
            self.flush()

    def malformed(self, raw: str) -> None:
        self.bad.write(f"{int(time.time()*1000)}\t{raw[:2000]}\n")

    def flush(self) -> None:
        for f, _ in self.files.values():
            f.flush()
        self.bad.flush()
        self.last_flush = time.time()

    def close(self) -> None:
        for f, _ in self.files.values():
            f.close()
        self.files = {}
        self.bad.close()


def csv_to_parquet(folder: Path, log_fn=log) -> tuple[int, list[str]]:
    """folder 아래(재귀) 모든 csv → parquet(zstd, 전 열 문자열). 성공한 csv 는 지운다. (바꾼 수, 실패 파일들)."""
    try:
        import pyarrow as pa
        import pyarrow.csv as pcsv
        import pyarrow.parquet as pq
    except ImportError:
        log_fn("pyarrow 없음 — csv 그대로 둠(용량 6~10배)")
        return 0, []
    n, failed = 0, []
    for p in sorted(folder.rglob("*.csv")):
        try:
            with open(p, encoding="utf-8") as f:
                header = f.readline().rstrip("\r\n").split(",")
            if not header or header == [""]:
                continue
            tbl = pcsv.read_csv(p, convert_options=pcsv.ConvertOptions(column_types={h: pa.string() for h in header}))
            pq.write_table(tbl, p.with_suffix(".parquet"), compression="zstd")
            p.unlink()
            n += 1
        except Exception as exc:  # noqa: BLE001
            failed.append(p.name)
            log_fn(f"parquet 변환 실패 {p.name}: {type(exc).__name__}")
    return n, failed


# ---------------------------------------------------------------- 보조

def parse_until(s: str) -> datetime:
    hh, mm = s.split(":")
    return now_kst().replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)


def build_subs(codes: list[str], mode: str, limit: int = kc.PER_CONN_LIMIT) -> list[tuple[str, str]]:
    """등록 목록(한도 안): both 면 첫 종목에 호가+체결, 남는 자리는 다음 종목 호가. asp 면 종목마다 호가 하나."""
    subs: list[tuple[str, str]] = []
    for i, c in enumerate(codes):
        if len(subs) >= limit:
            break
        subs.append(("H0STASP0", c))
        if mode == "both" and i == 0 and len(subs) < limit:
            subs.append(("H0STCNT0", c))
    return subs


def max_codes(mode: str, limit: int = kc.PER_CONN_LIMIT) -> int:
    return limit - 1 if mode == "both" else limit


def resolve_codes(a, limit: int) -> list[str]:
    if a.codes:
        codes = [c.strip().zfill(6) for c in a.codes.split(",") if c.strip()]
    elif a.picks == "auto":
        from kis_pick import today_picks
        codes = today_picks(a.config, limit, log=log, out_dir=Path(a.out))
    elif a.picks:
        codes = [ln.strip().zfill(6) for ln in Path(a.picks).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    else:
        raise SystemExit("--codes 또는 --picks 를 주세요")
    codes = [c for c in dict.fromkeys(codes) if kc.CODE_RE.match(c)]
    if len(codes) > limit:
        log(f"종목 {len(codes)}개 → 한도 {limit}개로 자름")
        codes = codes[:limit]
    return codes


def _pid_alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0); return True
        except OSError:
            return False
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    ctypes.windll.kernel32.CloseHandle(h)
    return True


class Lock:
    """같은 앱키로 두 프로세스가 붙으면 서로를 끊으므로 하나만 돌게 한다."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __enter__(self):
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip() or 0)
            except ValueError:
                pid = 0
            if pid and pid != os.getpid() and _pid_alive(pid):
                raise SystemExit(f"이미 녹음 중(PID {pid}) — 같은 앱키로 두 개를 돌리면 서로 끊긴다")
        self.path.write_text(str(os.getpid()))
        return self

    def __exit__(self, *exc):
        try:
            self.path.unlink()
        except OSError:
            pass


class KeepAwake:
    """녹음 중 PC 절전 방지(윈도우). 끝나면 해제."""
    ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001

    def __enter__(self):
        if sys.platform == "win32":
            ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED)
        return self

    def __exit__(self, *exc):
        if sys.platform == "win32":
            ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)


def notify(cfg_path: str, text: str) -> None:
    """config.yaml 에 telegram_bot_token·telegram_chat_id 가 있으면 한 줄 보낸다(없으면 조용히 넘어감). 값은 찍지 않는다."""
    try:
        import yaml
        d = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8")) or {}
        token, chat = str(d.get("telegram_bot_token", "") or ""), str(d.get("telegram_chat_id", "") or "")
        if not token or not chat:
            return
        from automations.common.telegram_bot import send_message
        send_message(token, chat, text)
    except Exception as exc:  # noqa: BLE001
        log(f"텔레그램 보내기 실패: {type(exc).__name__}")


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(DEFAULT_CFG))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--codes", default="")
    ap.add_argument("--picks", default="")
    ap.add_argument("--until", default="15:35")
    ap.add_argument("--minutes", type=float, default=0, help="지금부터 N분만(시험용, --until 대신)")
    ap.add_argument("--mode", choices=("asp", "both"), default="both", help="asp: 호가만(3종목), both: 첫 종목 호가+체결, 둘째 호가")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--no-parquet", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    with Lock(out / "record.lock"):
        return _run(a, out)


def _run(a, out: Path) -> int:
    kc.load_secrets(a.config)
    limit = max_codes(a.mode)
    codes = resolve_codes(a, limit)
    if not codes:
        log("종목이 없어 종료"); notify(a.config, "호가 녹음: 종목 0개 — 시작 못 함")
        return 3
    start = now_kst()
    until = start + timedelta(minutes=a.minutes) if a.minutes else parse_until(a.until)
    day_dir = out / start.strftime("%Y-%m-%d")
    run_dir = day_dir / f"run_{start:%H%M%S}"
    n_prev, _ = csv_to_parquet(out) if not a.no_parquet else (0, [])   # 앞선 실행이 남긴 csv 정리
    if n_prev:
        log(f"남아 있던 csv {n_prev}개를 parquet 으로 바꿈")
    subs = build_subs(codes, a.mode)
    used = list(dict.fromkeys(c for _, c in subs))
    log(f"종목 {len(used)}개({', '.join(used)}), 등록 {len(subs)}건, 종료 {until:%H:%M:%S}, 저장 {run_dir}")

    try:
        kc.approval_key_with_retry(log=log)
    except RuntimeError as exc:
        log(str(exc)); notify(a.config, f"호가 녹음 시작 실패: {exc}")
        return 4
    log("접속키 발급 확인")
    if a.dry:
        return 0

    store = DayStore(run_dir)
    stats = kc.SessionStats()
    deadline = start.replace(hour=9, minute=5, second=0, microsecond=0) if start.hour < 9 else None
    outcome = "정상"
    with KeepAwake():
        try:
            asyncio.run(kc.run_session(lambda: kc.approval_key_with_retry(log=log, max_wait=300), subs, store.write, until, stats,
                                       log=log, no_data_deadline=deadline, on_malformed=store.malformed))
        except kc.NoDataError:
            outcome = "휴장 추정(09:05 까지 데이터 없음)"
        except kc.StorageError as exc:
            outcome = f"저장 오류: {exc}"
        except KeyboardInterrupt:
            outcome = "키보드 중단"
        except RuntimeError as exc:
            outcome = f"중단: {exc}"
        finally:
            store.flush(); store.close()
    per_code = {}
    for (tr, code), n in stats.records.items():
        per_code.setdefault(code, {})[kc.TR_NAME.get(tr, tr)] = n
    summary = {
        "date": day_dir.name, "run": run_dir.name, "outcome": outcome, "codes": used, "mode": a.mode, "until": until.strftime("%H:%M:%S"),
        "seconds": round((now_kst() - start).total_seconds()), "connects": stats.connects, "frames": stats.frames, "rows": store.n,
        "per_code": per_code, "subscribe_ok": stats.subscribe_ok, "subscribe_failed": {f"{k[0]} {k[1]}": v for k, v in stats.subscribe_failed.items()},
        "key_reissues": stats.key_reissues, "idle_pings": stats.idle_pings, "idle_reconnects": stats.idle_reconnects,
        "encrypted_dropped": stats.encrypted_dropped, "malformed": stats.malformed, "bad_code_rows": stats.bad_code_rows, "alignment": stats.alignment,
        "widths": stats.widths, "gaps": [(datetime.fromtimestamp(x).strftime("%H:%M:%S"), datetime.fromtimestamp(y).strftime("%H:%M:%S")) for x, y in stats.gaps],
        "errors": stats.errors[-30:],
    }
    if not a.no_parquet:
        n_pq, failed = csv_to_parquet(run_dir)
        summary["parquet_files"], summary["parquet_failed"] = n_pq, failed
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    safe = {k: summary[k] for k in ("date", "run", "outcome", "seconds", "connects", "frames", "rows", "subscribe_ok", "key_reissues", "idle_reconnects", "malformed", "alignment")}
    safe["codes_n"], safe["gaps_n"], safe["errors_n"] = len(used), len(stats.gaps), len(stats.errors)
    (run_dir / "safe_summary.json").write_text(json.dumps(safe, ensure_ascii=False, indent=1), encoding="utf-8")
    line = f"호가 녹음 {day_dir.name}: {outcome}, 종목 {len(used)}개, 행 {store.n:,}, 연결 {stats.connects}회, 끊김 {len(stats.gaps)}회, 오류 {len(stats.errors)}건, 정렬 {stats.alignment or '-'}"
    log(line)
    if not a.minutes:
        notify(a.config, line)
    return 0 if store.n > 0 else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — traceback(지역변수)이 로그에 남지 않게 종류만
        log(f"실패: {type(exc).__name__}: {str(exc)[:80]}")
        sys.exit(5)
