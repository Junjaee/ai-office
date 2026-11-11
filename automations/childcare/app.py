"""시간제보육 예약기 — 창에서 설정하고 [시작]을 누르면 정각까지 기다렸다가 쏜다.

exe 로 만들어 쓴다(build_exe.cmd). 창은 파이썬에 들어 있는 tkinter 라 따로 깔 게 없다.

흐름:
    [크롬 열기] → 사람이 로그인(인증서/아이디) → [시작]
        → 매크로가 그 크롬에 붙음 → 예약 화면까지 미리 진입해 대기
        → 아이사랑 서버 시각으로 보정 → 09:00:00.000 발사
        → 1순위 실패하면 곧바로 2순위

설정은 %LOCALAPPDATA%\\childcare-macro\\settings.json 에 남는다(저장소에 올라가지 않는다).
"""
from __future__ import annotations

import calendar
import json
import os
import queue
import subprocess
import time
import threading
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

import childcare_site as site
import launcher

SETTINGS_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "childcare-macro"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
CHROME_PROFILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "childcare-chrome"

# 처음 쓸 때 보일 기본값. 창에서 고치면 settings.json 에 남는다.
DEFAULTS = {
    "centers": [
        {"name": "힐스송파어린이집", "code": "11710000741", "sido": "서울특별시", "gugun": "송파구"},
        {"name": "위례별마루어린이집", "code": "11710000744", "sido": "서울특별시", "gugun": "송파구"},
        {"name": "송파구육아종합지원센터", "code": "11710000705", "sido": "서울특별시", "gugun": "송파구"},
        {"name": "파크하비오어린이집", "code": "11710000743", "sido": "서울특별시", "gugun": "송파구"},
        {"name": "잠실어린이집", "code": "11710000366", "sido": "서울특별시", "gugun": "송파구"},
    ],
    "first": "힐스송파어린이집",
    "second": "위례별마루어린이집",
    "use_date": "",
    "begin": "09:30",
    "end": "13:30",
    "open_at": "09:00:00",
    "lead_ms": 150,
    # 오픈 시각을 정확히 모른다(자료마다 다르고 기관마다 다를 수 있다).
    # 그래서 예상 시각 전부터 "열렸나?"를 가볍게 확인하다가, 열리는 순간 쏜다.
    # 미리 신청을 쏘지는 않는다 — 오픈 전 신청은 거절되고 쌓이면 차단된다.
    "watch_before_sec": 60,
    "watch_interval_ms": 500,
}


def load_settings() -> dict:
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return data


def save_settings(data: dict) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def open_chrome() -> None:
    """예약 전용 크롬을 디버그 포트로 띄운다. 이미 떠 있으면 크롬이 알아서 창만 하나 더 연다."""
    for candidate in (
        Path(os.environ.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
    ):
        if candidate.exists():
            subprocess.Popen([
                str(candidate),
                f"--remote-debugging-port={launcher.CDP_PORT}",
                f"--user-data-dir={CHROME_PROFILE}",
                site.MENU_RESERVE,
            ])
            return
    raise RuntimeError("크롬을 못 찾았어요")


def default_use_date(saved: str, now: datetime | None = None) -> str:
    """이용일 기본값(YYYY-MM-DD). 저장된 날짜가 지났으면 오늘로부터 14일 뒤로 되돌린다.

    독립반은 늘 '14일 뒤'가 열리므로, 앱을 새로 켜면 오늘 열리는 날짜가 저절로 들어간다.
    """
    now = now or datetime.now(launcher.KST)
    today = now.date()
    try:
        picked = datetime.strptime(saved, "%Y-%m-%d").date()
        if picked >= today:
            return picked.isoformat()
    except (TypeError, ValueError):
        pass
    return (today + timedelta(days=14)).isoformat()


class DatePicker(tk.Toplevel):
    """달 하나를 보여 주는 작은 달력. 고른 날짜를 entry 에 넣는다."""

    def __init__(self, parent, entry: "ttk.Entry") -> None:
        super().__init__(parent)
        self.title("이용일 고르기")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.entry = entry
        try:
            picked = datetime.strptime(entry.get().strip(), "%Y-%m-%d").date()
        except ValueError:
            picked = datetime.now(launcher.KST).date()
        self.year, self.month = picked.year, picked.month
        self.body = ttk.Frame(self)
        self.body.grid(row=0, column=0, padx=10, pady=10)
        self._draw()

    def _draw(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        ttk.Button(self.body, text="◀", width=3, command=lambda: self._shift(-1)).grid(row=0, column=0)
        ttk.Label(self.body, text=f"{self.year}년 {self.month}월").grid(row=0, column=1, columnspan=5)
        ttk.Button(self.body, text="▶", width=3, command=lambda: self._shift(1)).grid(row=0, column=6)
        for i, name in enumerate("월화수목금토일"):
            ttk.Label(self.body, text=name, width=4, anchor="center").grid(row=1, column=i)
        today = datetime.now(launcher.KST).date()
        for r, week in enumerate(calendar.Calendar().monthdatescalendar(self.year, self.month), start=2):
            for c, day in enumerate(week):
                if day.month != self.month:
                    continue
                btn = ttk.Button(self.body, text=str(day.day), width=4,
                                 command=lambda d=day: self._pick(d))
                if day < today:
                    btn.state(["disabled"])
                btn.grid(row=r, column=c, padx=1, pady=1)

    def _shift(self, step: int) -> None:
        self.month += step
        if self.month < 1:
            self.year, self.month = self.year - 1, 12
        elif self.month > 12:
            self.year, self.month = self.year + 1, 1
        self._draw()

    def _pick(self, day) -> None:
        self.entry.delete(0, "end")
        self.entry.insert(0, day.isoformat())
        self.destroy()


def parse_open_at(text: str, now: datetime | None = None) -> datetime:
    """'09:00:00' → 다음 그 시각(KST). 오늘 그 시각이 지났으면 내일."""
    hh, mm, ss = (int(x) for x in text.strip().split(":"))
    now = now or datetime.now(launcher.KST)
    today = now.replace(hour=hh, minute=mm, second=ss, microsecond=0)
    return today if now < today else today + timedelta(days=1)


def run_macro(cfg: dict, log, stop: threading.Event) -> None:
    """[시작]을 누르면 도는 본체. log(한 줄) 로 창에 알린다."""
    from playwright.sync_api import sync_playwright

    by_name = {c["name"]: c for c in cfg["centers"]}
    picks = [n for n in (cfg["first"], cfg["second"]) if n and n in by_name]
    if not picks:
        raise RuntimeError("1순위 어린이집을 골라 주세요")

    open_at = parse_open_at(cfg["open_at"])
    picked = cfg["use_date"].strip()
    use_date = datetime.strptime(picked, "%Y-%m-%d").strftime("%Y%m%d")
    log(f"이용일 {picked} · {cfg['begin']}~{cfg['end']}")
    log(f"1순위 {picks[0]}" + (f" · 2순위 {picks[1]}" if len(picks) > 1 else ""))

    with sync_playwright() as p:
        log("크롬에 붙는 중…")
        browser, page = launcher.attach_chrome(p, go_to=site.MENU_RESERVE)
        try:
            if not site.is_logged_in(page):
                raise RuntimeError("로그인이 안 돼 있어요. 크롬에서 먼저 로그인해 주세요")
            log("로그인 확인됨")

            log("서버 시각 맞추는 중…")
            offset = launcher.server_offset_ms(page)
            log(f"이 PC 시계가 서버보다 {offset:+.0f}ms")

            log("예약 화면까지 미리 들어가는 중…")
            site.open_reserve_page(page, by_name[picks[0]])
            klass = site.open_apply_tab(page)
            log(f"준비 끝 — {picks[0]} · {klass[1]}반")

            watch_before = int(cfg["watch_before_sec"])
            launcher.sleep_until(open_at - timedelta(seconds=watch_before), offset, 0, log)
            log(f"감시 시작 — 열리는 순간 쏩니다 ({cfg['watch_interval_ms']}ms 간격)")

            def fire(why: str) -> bool:
                """1순위부터 차례로 신청. 한 곳이라도 되면 True.

                1순위는 이미 화면이 열려 있어 곧바로 쏜다. 2순위는 그 기관 화면으로
                옮겨 가야 해서 몇 초 걸린다(반 코드가 기관마다 다르다).
                """
                nonlocal klass
                for i, name in enumerate(picks, 1):
                    log(f"{why} → {i}순위 {name} 발사")
                    try:
                        if i > 1:
                            site.open_reserve_page(page, by_name[name])
                            klass = site.open_apply_tab(page)
                        ok, note = site.reserve(page, klass, use_date, cfg["begin"], cfg["end"])
                    except Exception as exc:  # noqa: BLE001 - 한 곳이 터져도 다음 곳은 쏴 본다
                        log(f"  {name} 오류 — {str(exc)[:80]}")
                        continue
                    log(("  성공 — " if ok else "  실패 — ") + note)
                    if ok:
                        return True
                return False

            # 예상 정각(서버 기준)에 도착하도록 보정한 발사 시각
            fire_at = open_at.timestamp() + (offset - float(cfg["lead_ms"])) / 1000.0
            give_up = fire_at + int(cfg.get("watch_grace_sec", 120))
            interval = int(cfg["watch_interval_ms"]) / 1000.0
            shot_at_open = False

            while not stop.is_set() and time.time() < give_up:
                # 보험 한 발 — 조회로는 안 보여도 신청은 되는 경우가 있다
                if not shot_at_open and time.time() >= fire_at:
                    shot_at_open = True
                    if fire("예상 정각"):
                        return
                try:
                    if site.is_open(page, use_date, cfg["begin"]):
                        if fire("열림 확인"):
                            return
                except Exception as exc:  # noqa: BLE001 - 조회가 한 번 튕겨도 감시는 계속한다
                    log(f"확인 실패(계속 감시) — {str(exc)[:60]}")
                time.sleep(interval)

            log("멈췄어요" if stop.is_set() else "시간 안에 못 잡았어요")
        finally:
            browser.close()


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("시간제보육 예약기")
        self.resizable(False, False)
        self.cfg = load_settings()
        self.msgs: queue.Queue[str] = queue.Queue()
        self.stop = threading.Event()
        self.worker: threading.Thread | None = None
        self._build()
        self.after(100, self._drain)

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}
        names = [c["name"] for c in self.cfg["centers"]]
        frm = ttk.Frame(self)
        frm.grid(row=0, column=0, sticky="we", padx=10, pady=10)

        ttk.Label(frm, text="1순위").grid(row=0, column=0, sticky="w", **pad)
        self.first = ttk.Combobox(frm, values=names, width=26, state="readonly")
        self.first.set(self.cfg["first"])
        self.first.grid(row=0, column=1, columnspan=3, sticky="w", **pad)

        ttk.Label(frm, text="2순위").grid(row=1, column=0, sticky="w", **pad)
        self.second = ttk.Combobox(frm, values=[""] + names, width=26, state="readonly")
        self.second.set(self.cfg["second"])
        self.second.grid(row=1, column=1, columnspan=3, sticky="w", **pad)

        ttk.Label(frm, text="이용 시간").grid(row=2, column=0, sticky="w", **pad)
        self.begin = ttk.Entry(frm, width=8)
        self.begin.insert(0, self.cfg["begin"])
        self.begin.grid(row=2, column=1, sticky="w", **pad)
        ttk.Label(frm, text="~").grid(row=2, column=2)
        self.end = ttk.Entry(frm, width=8)
        self.end.insert(0, self.cfg["end"])
        self.end.grid(row=2, column=3, sticky="w", **pad)

        ttk.Label(frm, text="이용일").grid(row=3, column=0, sticky="w", **pad)
        self.use_date = ttk.Entry(frm, width=12)
        self.use_date.insert(0, default_use_date(self.cfg.get("use_date", "")))
        self.use_date.grid(row=3, column=1, sticky="w", **pad)
        ttk.Button(frm, text="달력", width=6,
                   command=lambda: DatePicker(self, self.use_date)).grid(row=3, column=2, columnspan=2, sticky="w", **pad)

        ttk.Label(frm, text="오픈 시각").grid(row=4, column=0, sticky="w", **pad)
        self.open_at = ttk.Entry(frm, width=12)
        self.open_at.insert(0, self.cfg["open_at"])
        self.open_at.grid(row=4, column=1, sticky="w", **pad)

        ttk.Label(frm, text="미리 감시").grid(row=5, column=0, sticky="w", **pad)
        self.watch_before = ttk.Entry(frm, width=5)
        self.watch_before.insert(0, str(self.cfg["watch_before_sec"]))
        self.watch_before.grid(row=5, column=1, sticky="w", **pad)
        ttk.Label(frm, text="초 전부터").grid(row=5, column=2, sticky="w", **pad)
        self.watch_interval = ttk.Entry(frm, width=5)
        self.watch_interval.insert(0, str(self.cfg["watch_interval_ms"]))
        self.watch_interval.grid(row=5, column=3, sticky="w", **pad)
        ttk.Label(frm, text="ms 간격").grid(row=5, column=4, sticky="w", **pad)

        btns = ttk.Frame(self)
        btns.grid(row=1, column=0, sticky="we", padx=16)
        ttk.Button(btns, text="크롬 열기", command=self._open_chrome).grid(row=0, column=0, padx=4)
        self.start_btn = ttk.Button(btns, text="시작", command=self._start)
        self.start_btn.grid(row=0, column=1, padx=4)
        ttk.Button(btns, text="멈춤", command=lambda: self.stop.set()).grid(row=0, column=2, padx=4)

        self.log_box = tk.Text(self, height=12, width=52, state="disabled", wrap="word")
        self.log_box.grid(row=2, column=0, padx=16, pady=10)
        self._log("크롬 열기 → 로그인 → 시작 순서로 누르세요")

    def _log(self, line: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{datetime.now():%H:%M:%S}  {line}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _drain(self) -> None:
        while not self.msgs.empty():
            self._log(self.msgs.get())
        if self.worker and not self.worker.is_alive():
            self.worker = None
            self.start_btn.configure(state="normal")
        self.after(100, self._drain)

    def _collect(self) -> dict:
        cfg = dict(self.cfg)
        cfg.update({
            "first": self.first.get(),
            "second": self.second.get(),
            "begin": self.begin.get().strip(),
            "end": self.end.get().strip(),
            "open_at": self.open_at.get().strip(),
            "use_date": self.use_date.get().strip(),
            "watch_before_sec": int(self.watch_before.get().strip() or 60),
            "watch_interval_ms": int(self.watch_interval.get().strip() or 500),
        })
        return cfg

    def _open_chrome(self) -> None:
        try:
            open_chrome()
            self._log("크롬을 띄웠어요. 거기서 로그인하세요")
        except Exception as exc:  # noqa: BLE001 - 창에 그대로 보여 준다
            messagebox.showerror("크롬 열기", str(exc))

    def _start(self) -> None:
        if self.worker:
            return
        try:
            self.cfg = self._collect()
            save_settings(self.cfg)
        except ValueError:
            messagebox.showerror("설정", "시간은 09:30, 오픈 시각은 09:00:00 처럼 적어 주세요")
            return
        self.stop.clear()
        self.start_btn.configure(state="disabled")

        def work() -> None:
            try:
                run_macro(self.cfg, self.msgs.put, self.stop)
            except Exception as exc:  # noqa: BLE001 - 창에 한 줄로 알린다
                self.msgs.put(f"멈춤 — {exc}")

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()


if __name__ == "__main__":
    App().mainloop()
