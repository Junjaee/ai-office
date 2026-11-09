"""바깥에서 받아오는 것: S&P 500 구성종목(위키), 시세(야후), 회사번호(SEC), 재무 묶음(SEC)."""
from __future__ import annotations

import io
import json
import os
import time
from pathlib import Path

import pandas as pd
import requests

WIKI = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SEC_FACTS_ZIP = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
BENCH = ["SPY", "^VIX", "KRW=X"]
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"


def _get(url: str, ua: str, retries: int = 3, delay: float = 1.0, timeout: int = 60, **kw) -> requests.Response:
    last = ""
    for attempt in range(retries):
        try:
            res = requests.get(url, headers={"User-Agent": ua}, timeout=timeout, **kw)
            if res.status_code == 200:
                return res
            last = f"HTTP {res.status_code}"
        except requests.exceptions.RequestException as exc:
            last = type(exc).__name__
        time.sleep(delay * (attempt + 1))
    raise RuntimeError(f"자료 요청 실패 {url.split('/')[2]}: {last}")


def members(ua: str = BROWSER_UA) -> pd.DataFrame:
    """위키 표 → 티커(야후식 '-'), 회사명, 업종, CIK. 주식 종류가 둘인 회사는 첫 것만."""
    html = _get(WIKI, ua).text
    t = pd.read_html(io.StringIO(html))[0]
    df = pd.DataFrame({
        "ticker": t["Symbol"].astype(str).str.replace(".", "-", regex=False),
        "name": t["Security"].astype(str),
        "sector": t["GICS Sector"].astype(str),
        "cik": pd.to_numeric(t["CIK"], errors="coerce"),
    })
    df = df.drop_duplicates(subset="cik", keep="first") if df["cik"].notna().all() else df
    if len(df) < 450:
        raise RuntimeError(f"자료 요청 실패 위키 구성종목: {len(df)}개뿐")
    return df.reset_index(drop=True)


def cik_map(df: pd.DataFrame, sec_ua: str) -> dict[str, int]:
    """티커 → CIK. 위키에 있으면 그것, 없으면 SEC 목록에서."""
    out = {r.ticker: int(r.cik) for r in df.itertuples() if pd.notna(r.cik)}
    missing = [t for t in df["ticker"] if t not in out]
    if missing:
        sec = _get(SEC_TICKERS, sec_ua).json()
        by_t = {v["ticker"].replace(".", "-"): int(v["cik_str"]) for v in sec.values()}
        out.update({t: by_t[t] for t in missing if t in by_t})
    return out


def prices(tickers: list[str], period: str = "18mo", threads: bool = True) -> tuple[pd.DataFrame, list[str]]:
    """야후 일별 종가(분할·배당 반영). (종가표, 못 받은 티커). 야후가 막으면 RuntimeError."""
    import yfinance as yf  # 무거운 모듈이라 여기서만

    want = list(dict.fromkeys(list(tickers) + BENCH))
    try:
        d = yf.download(want, period=period, interval="1d", auto_adjust=True, group_by="column",
                        threads=threads, progress=False)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"시세 수집 실패: {type(exc).__name__}") from None
    close = d["Close"] if "Close" in d else pd.DataFrame()
    if close.empty or "SPY" not in close or close["SPY"].dropna().empty:
        raise RuntimeError("시세 수집 실패: SPY 조차 받지 못함 (야후가 요청을 막았을 수 있음)")
    close.index = close.index.tz_localize(None) if close.index.tz is not None else close.index
    close = close[close["SPY"].notna()].copy()
    failed = [t for t in want if t not in close or close[t].dropna().empty]
    if failed:
        time.sleep(3)
        try:
            d2 = yf.download(failed, period=period, interval="1d", auto_adjust=True, group_by="column",
                             threads=False, progress=False)
            c2 = d2["Close"] if "Close" in d2 else pd.DataFrame()
            if len(failed) == 1 and not c2.empty and failed[0] not in c2:
                c2 = c2.rename(columns={c2.columns[0]: failed[0]})
            for t in failed:
                if t in c2 and not c2[t].dropna().empty:
                    close[t] = c2[t].reindex(close.index)
        except Exception:  # noqa: BLE001
            pass
        failed = [t for t in want if t not in close or close[t].dropna().empty]
    return close, failed


def download_facts(dest: str, sec_ua: str, progress=None) -> str:
    """SEC 재무 묶음(약 1.4GB)을 dest 에 내려받는다. 이미 있고 3일 안 됐으면 그대로 쓴다."""
    p = Path(dest)
    if p.exists() and p.stat().st_size > 500_000_000 and time.time() - p.stat().st_mtime < 3 * 86400:
        return str(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    with requests.get(SEC_FACTS_ZIP, headers={"User-Agent": sec_ua}, stream=True, timeout=120) as res:
        if res.status_code != 200:
            raise RuntimeError(f"SEC 요청 실패: HTTP {res.status_code} (접속 표시가 이름+메일 형식인지 확인)")
        total = int(res.headers.get("Content-Length") or 0)
        got = 0
        step = 0
        with open(tmp, "wb") as f:
            for chunk in res.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                got += len(chunk)
                if progress and total and got * 10 // total > step:
                    step = got * 10 // total
                    progress(f"SEC 재무 묶음 {step * 10}% ({got / 1e9:.2f}GB)")
    os.replace(tmp, p)
    return str(p)


def save_json(path: str, data) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
