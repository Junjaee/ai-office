"""한국투자증권 KIS Developers 웹소켓 — 실시간 호가(H0STASP0)·체결(H0STCNT0) 수신 클라이언트.

설계: docs/superpowers/specs/2026-09-28-호가-녹음-design.md
- 비밀값은 환경변수 KIS_APP_KEY·KIS_APP_SECRET 로만 받는다. load_secrets() 가 개인 폴더의 config.yaml 을 읽어 넣는다. 값은 어디에도 찍지 않는다.
  녹음기는 계좌번호를 쓰지 않는다(주문 기능이 없다). **DEBUG 로깅 금지** — websockets 로거가 구독 프레임(접속키 포함)을 통째로 찍는다.
- 접속키(approval_key)는 REST /oauth2/Approval 로 받는다. 구독이 전부 거절되거나 연결 실패가 이어지면 새로 받는다.
- 메시지 형식(공식 예제 kis_auth.py 기준): 데이터 프레임 "0|TR_ID|건수|필드^필드^..." (여러 건이면 필드가 건수 배). 접두 '1' 은 암호화 프레임(호가·체결은
  비암호화라 오지 않아야 함) → 세고 버린다. 그 밖은 JSON 제어 메시지(구독 응답·PINGPONG). PINGPONG 은 같은 내용으로 pong 한다.
- 실측(2026-09-28, 실전 앱키): 연결 하나에 등록 3건(4번째부터 MAX SUBSCRIBE OVER), 앱키당 연결 1개(새 연결이 붙으면 앞 연결이 끊긴다).
  실제 필드 수는 문서보다 많다(호가 63·체결 47; 문서 59·46). 초과분은 EXTRA1.. 로 이름 붙이고, 그 뜻은 아직 확인하지 못했다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import websockets

logging.getLogger("websockets").setLevel(logging.WARNING)   # 프레임(접속키)이 로그에 찍히지 않게

REST_URL = "https://openapi.koreainvestment.com:9443"
WS_URL = "ws://ops.koreainvestment.com:21000/tryitout"     # 공식 예제 형식(도메인 + /tryitout). 2026-09-28 실측 성공
MAX_REGISTRATIONS = 40          # 공식 예제의 상한
PER_CONN_LIMIT = 3              # 실측 상한(계정에 따라 다를 수 있음 → README 의 확인 절차)
KEY_MAX_AGE_SEC = 20 * 3600     # 접속키를 이 시간 넘게 쓰지 않는다(공식 예제는 24시간마다 재발급)
CODE_RE = re.compile(r"^[0-9A-Z]{6}$")

FIELDS = {
    "H0STASP0": [  # 국내주식 실시간호가 (KRX) [실시간-004], 문서 59개
        "MKSC_SHRN_ISCD", "BSOP_HOUR", "HOUR_CLS_CODE",
        "ASKP1", "ASKP2", "ASKP3", "ASKP4", "ASKP5", "ASKP6", "ASKP7", "ASKP8", "ASKP9", "ASKP10",
        "BIDP1", "BIDP2", "BIDP3", "BIDP4", "BIDP5", "BIDP6", "BIDP7", "BIDP8", "BIDP9", "BIDP10",
        "ASKP_RSQN1", "ASKP_RSQN2", "ASKP_RSQN3", "ASKP_RSQN4", "ASKP_RSQN5", "ASKP_RSQN6", "ASKP_RSQN7", "ASKP_RSQN8", "ASKP_RSQN9", "ASKP_RSQN10",
        "BIDP_RSQN1", "BIDP_RSQN2", "BIDP_RSQN3", "BIDP_RSQN4", "BIDP_RSQN5", "BIDP_RSQN6", "BIDP_RSQN7", "BIDP_RSQN8", "BIDP_RSQN9", "BIDP_RSQN10",
        "TOTAL_ASKP_RSQN", "TOTAL_BIDP_RSQN", "OVTM_TOTAL_ASKP_RSQN", "OVTM_TOTAL_BIDP_RSQN",
        "ANTC_CNPR", "ANTC_CNQN", "ANTC_VOL", "ANTC_CNTG_VRSS", "ANTC_CNTG_VRSS_SIGN",
        "ANTC_CNTG_PRDY_CTRT", "ACML_VOL", "TOTAL_ASKP_RSQN_ICDC", "TOTAL_BIDP_RSQN_ICDC",
        "OVTM_TOTAL_ASKP_ICDC", "OVTM_TOTAL_BIDP_ICDC", "STCK_DEAL_CLS_CODE",
    ],
    "H0STCNT0": [  # 국내주식 실시간체결가 (KRX) [실시간-003], 문서 46개
        "MKSC_SHRN_ISCD", "STCK_CNTG_HOUR", "STCK_PRPR", "PRDY_VRSS_SIGN", "PRDY_VRSS", "PRDY_CTRT", "WGHN_AVRG_STCK_PRC", "STCK_OPRC",
        "STCK_HGPR", "STCK_LWPR", "ASKP1", "BIDP1", "CNTG_VOL", "ACML_VOL", "ACML_TR_PBMN", "SELN_CNTG_CSNU", "SHNU_CNTG_CSNU", "NTBY_CNTG_CSNU",
        "CTTR", "SELN_CNTG_SMTN", "SHNU_CNTG_SMTN", "CCLD_DVSN", "SHNU_RATE", "PRDY_VOL_VRSS_ACML_VOL_RATE", "OPRC_HOUR", "OPRC_VRSS_PRPR_SIGN",
        "OPRC_VRSS_PRPR", "HGPR_HOUR", "HGPR_VRSS_PRPR_SIGN", "HGPR_VRSS_PRPR", "LWPR_HOUR", "LWPR_VRSS_PRPR_SIGN", "LWPR_VRSS_PRPR", "BSOP_DATE",
        "NEW_MKOP_CLS_CODE", "TRHT_YN", "ASKP_RSQN1", "BIDP_RSQN1", "TOTAL_ASKP_RSQN", "TOTAL_BIDP_RSQN", "VOL_TNRT",
        "PRDY_SMNS_HOUR_ACML_VOL", "PRDY_SMNS_HOUR_ACML_VOL_RATE", "HOUR_CLS_CODE", "MRKT_TRTM_CLS_CODE", "VI_STND_PRC",
    ],
}
TR_NAME = {"H0STASP0": "호가", "H0STCNT0": "체결"}


class StorageError(RuntimeError):
    """저장(디스크) 오류 — 재연결로 풀리지 않으니 세션을 끝낸다."""


class NoDataError(RuntimeError):
    """정한 시각까지 데이터 프레임이 하나도 없음(휴장 또는 구독 실패)."""


# ---------------------------------------------------------------- 비밀값·인증

def load_secrets(cfg_path: str | Path) -> None:
    """개인 폴더 config.yaml 의 kis_app_key·kis_app_secret 을 환경변수로 넣는다(값을 돌려주지도 찍지도 않는다). 형식만 검사."""
    import yaml
    data = yaml.safe_load(Path(cfg_path).read_text(encoding="utf-8")) or {}
    for key, env, min_len in (("kis_app_key", "KIS_APP_KEY", 20), ("kis_app_secret", "KIS_APP_SECRET", 50)):
        v = str(data.get(key, "") or "").strip().strip('"').strip("'")
        if not v or v.startswith("여기에"):
            raise SystemExit(f"config.yaml 의 {key} 가 비어 있거나 자리표시자입니다 — KIS Developers 에서 발급한 값으로 바꿔 주세요")
        if len(v) < min_len or not re.fullmatch(r"[A-Za-z0-9+/=_\-]+", v):
            raise SystemExit(f"config.yaml 의 {key} 형식이 이상합니다(길이 {len(v)}) — 앞뒤 공백·줄바꿈을 확인해 주세요")
        os.environ[env] = v


def get_approval_key(timeout: float = 15.0) -> str:
    """웹소켓 접속키 발급. 실패하면 종류만 담은 RuntimeError(키·본문은 절대 메시지에 넣지 않는다)."""
    import requests
    try:
        r = requests.post(f"{REST_URL}/oauth2/Approval", timeout=timeout, headers={"Content-Type": "application/json"},
                          json={"grant_type": "client_credentials", "appkey": os.environ["KIS_APP_KEY"], "secretkey": os.environ["KIS_APP_SECRET"]})
    except requests.RequestException as exc:
        raise RuntimeError(f"접속키 발급 실패: {type(exc).__name__}") from None
    if r.status_code != 200:
        raise RuntimeError(f"접속키 발급 실패: HTTP {r.status_code}")
    try:
        key = (r.json() or {}).get("approval_key")
    except ValueError:
        raise RuntimeError("접속키 발급 실패: 응답이 JSON 이 아님") from None
    if not key:
        raise RuntimeError("접속키 발급 실패: 응답에 approval_key 없음")
    return key


def approval_key_with_retry(log: Callable[[str], None] = print, max_wait: float = 600.0) -> str:
    """지수 백오프(5→60초)로 최대 max_wait 초 동안 재시도. PC 가 깨어난 직후 네트워크가 늦어도 하루를 잃지 않게."""
    t0, wait = time.time(), 5.0
    while True:
        try:
            return get_approval_key()
        except RuntimeError as exc:
            if time.time() - t0 + wait > max_wait:
                raise
            log(f"{exc} — {wait:.0f}초 뒤 다시")
            time.sleep(wait)
            wait = min(wait * 2, 60.0)


# ---------------------------------------------------------------- 메시지

def subscribe_msg(approval_key: str, tr_id: str, tr_key: str, tr_type: str = "1") -> str:
    """구독(tr_type=1)·해제(2) 요청 JSON."""
    return json.dumps({
        "header": {"approval_key": approval_key, "custtype": "P", "tr_type": tr_type, "content-type": "utf-8"},
        "body": {"input": {"tr_id": tr_id, "tr_key": tr_key}},
    })


@dataclass
class Frame:
    kind: str                  # "data" | "system" | "pingpong" | "encrypted" | "malformed" | "unknown"
    tr_id: str = ""
    tr_key: str = ""
    records: list[list[str]] = field(default_factory=list)
    raw: str = ""
    rt_cd: str = ""
    msg: str = ""


def parse_frame(raw: str, widths: dict | None = None) -> Frame:
    """수신 문자열 하나 → Frame.

    widths: {tr_id: 필드 폭} — 처음 나눠떨어진 프레임에서 배우고, 뒤에 폭이 다르면 malformed 로 분류한다(열 밀림 방지).
    """
    if not raw:
        return Frame("unknown", raw=raw)
    if raw[0] == "1":
        parts = raw.split("|", 3)
        return Frame("encrypted", tr_id=parts[1] if len(parts) > 1 else "", raw=raw)
    if raw[0] == "0":
        parts = raw.split("|", 3)
        if len(parts) < 4:
            return Frame("malformed", raw=raw)
        tr_id = parts[1]
        try:
            n = max(int(parts[2]), 1)
        except ValueError:
            return Frame("malformed", tr_id=tr_id, raw=raw)
        fields = parts[3].split("^")
        if len(fields) % n != 0:
            return Frame("malformed", tr_id=tr_id, raw=raw)
        w = len(fields) // n
        if widths is not None:
            known = widths.get(tr_id)
            if known is None:
                widths[tr_id] = w
            elif known != w:
                return Frame("malformed", tr_id=tr_id, raw=raw)
        return Frame("data", tr_id=tr_id, records=[fields[i * w:(i + 1) * w] for i in range(n)], raw=raw)
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        return Frame("unknown", raw=raw)
    header = d.get("header", {}) or {}
    tr_id = str(header.get("tr_id", ""))
    if tr_id == "PINGPONG":
        return Frame("pingpong", tr_id=tr_id, raw=raw)
    body = d.get("body", {}) or {}
    return Frame("system", tr_id=tr_id, tr_key=str(header.get("tr_key", "")), raw=raw,
                 rt_cd=str(body.get("rt_cd", "")), msg=re.sub(r"[^A-Z0-9 _]", "", str(body.get("msg1", "")).upper())[:40])


def columns_for(tr_id: str, width: int) -> list[str]:
    """문서의 필드 이름에 실측 초과분은 EXTRA1.. 로 이름 붙인다(문서보다 적으면 앞에서부터 자른다)."""
    base = list(FIELDS.get(tr_id, []))
    if width <= len(base):
        return base[:width]
    return base + [f"EXTRA{i}" for i in range(1, width - len(base) + 1)]


def records_to_rows(frame: Frame, recv_ms: int) -> tuple[list[dict], int]:
    """(행 목록, 종목코드가 이상해 버린 건수). 행 = recv_ms · seq(프레임 안 순번) · tr_id · 필드들."""
    rows, bad = [], 0
    for seq, rec in enumerate(frame.records):
        if not rec or not CODE_RE.match(rec[0]):
            bad += 1
            continue
        row = {"recv_ms": recv_ms, "seq": seq, "tr_id": frame.tr_id}
        row.update(zip(columns_for(frame.tr_id, len(rec)), rec))
        rows.append(row)
    return rows, bad


def alignment_check(row: dict) -> list[str]:
    """첫 데이터 프레임으로 열 정렬을 점검한다(초과 필드가 중간에 끼면 뒤 열이 밀린다). 어긋난 항목 이름 목록(비면 정상)."""
    bad = []
    try:
        if row["tr_id"] == "H0STASP0":
            a1, b1 = float(row["ASKP1"]), float(row["BIDP1"])
            if not (a1 > b1 > 0):
                bad.append("ASKP1>BIDP1")
            if sum(float(row[f"ASKP_RSQN{i}"]) for i in range(1, 11)) != float(row["TOTAL_ASKP_RSQN"]):
                bad.append("TOTAL_ASKP_RSQN")
            if not re.fullmatch(r"\d{6}", row["BSOP_HOUR"]):
                bad.append("BSOP_HOUR")
        elif row["tr_id"] == "H0STCNT0":
            if not re.fullmatch(r"\d{6}", row["STCK_CNTG_HOUR"]):
                bad.append("STCK_CNTG_HOUR")
            if not re.fullmatch(r"\d{8}", row["BSOP_DATE"]):
                bad.append("BSOP_DATE")
            if float(row["STCK_PRPR"]) <= 0 or float(row["CNTG_VOL"]) < 0:
                bad.append("STCK_PRPR/CNTG_VOL")
    except (KeyError, ValueError):
        bad.append("fields")
    return bad


# ---------------------------------------------------------------- 세션

@dataclass
class SessionStats:
    connects: int = 0
    frames: int = 0
    records: dict = field(default_factory=dict)     # (tr_id, code) → 건수
    subscribe_ok: int = 0
    subscribe_failed: dict = field(default_factory=dict)   # (tr_id, code) → 서버 응답
    key_reissues: int = 0
    idle_pings: int = 0
    idle_reconnects: int = 0
    encrypted_dropped: int = 0
    malformed: int = 0
    bad_code_rows: int = 0
    alignment: str = ""                                # "OK" | "FAIL: ..."
    errors: list = field(default_factory=list)
    gaps: list = field(default_factory=list)           # (끊긴 시각, 다시 붙은 시각)
    last_recv: float = 0.0
    widths: dict = field(default_factory=dict)


def _errline(exc: BaseException) -> str:
    text = str(exc)[:80].replace(str(Path.home()), "~")
    return f"{datetime.now():%H:%M:%S} {type(exc).__name__}: {text}"


async def run_session(get_key: Callable[[], str], subs: list[tuple[str, str]], on_rows: Callable[[list[dict]], None],
                      until: datetime, stats: SessionStats, log: Callable[[str], None] = print,
                      url: str = WS_URL, idle_timeout: float = 90.0, no_data_deadline: datetime | None = None,
                      max_consecutive_failures: int = 30, on_malformed: Callable[[str], None] | None = None) -> None:
    """until(로컬 시각)까지 웹소켓을 유지하며 subs 의 (tr_id, 종목코드)를 구독하고, 수신 건마다 on_rows(rows) 를 부른다.

    - 접속키는 get_key() 로 받는다. 구독이 전부 거절되거나 연결 실패가 3회 이어지거나 키가 20시간 넘으면 새로 받는다.
    - MAX SUBSCRIBE OVER 로 거절된 등록은 그 세션에서 빼고 기록한다. 그 밖의 거절(rt_cd≠0)은 접속키 문제로 보고 재연결.
    - 끊기면 지수 백오프(2→60초). 백오프는 첫 데이터 프레임을 받은 뒤에만 초기화한다. 연속 실패가 max_consecutive_failures 를 넘으면 포기.
    - idle_timeout 동안 메시지가 없으면 먼저 ping 으로 살아 있는지 묻고, 응답 없을 때만 다시 붙는다.
    - on_rows 가 OSError 를 내면 저장 문제이므로 StorageError 로 바로 끝낸다(재연결로 감추지 않는다).
    - no_data_deadline 이 지났는데 데이터 프레임이 0 이면 NoDataError(휴장 또는 구독 실패).
    """
    if len(subs) > MAX_REGISTRATIONS:
        raise ValueError(f"등록 {len(subs)}건 > 한도 {MAX_REGISTRATIONS}")
    active = list(subs)
    key, key_time = get_key(), time.time()
    backoff, consecutive_fail = 2.0, 0
    disconnected_at: float | None = None
    need_new_key = False
    while datetime.now() < until:
        if active == []:
            raise RuntimeError("등록할 것이 남지 않았습니다(전부 거절)")
        if need_new_key or time.time() - key_time > KEY_MAX_AGE_SEC:
            key, key_time = get_key(), time.time()
            stats.key_reissues += 1
            need_new_key = False
            log("접속키 재발급")
        got_data_this_conn = False
        try:
            async with websockets.connect(url, ping_interval=None, max_size=2**22) as ws:
                stats.connects += 1
                if disconnected_at is not None:
                    stats.gaps.append((disconnected_at, time.time()))
                    disconnected_at = None
                log(f"연결 {stats.connects}회차, 구독 {len(active)}건")
                pending = {(tr, c) for tr, c in active}
                for tr_id, code in active:
                    await ws.send(subscribe_msg(key, tr_id, code, "1"))
                    await asyncio.sleep(0.05)
                ok_this_conn = 0
                while datetime.now() < until:
                    remaining = (until - datetime.now()).total_seconds()
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, min(idle_timeout, remaining)))
                    except asyncio.TimeoutError:
                        if datetime.now() >= until:
                            break
                        if no_data_deadline and stats.frames == 0 and datetime.now() > no_data_deadline:
                            raise NoDataError("데이터 프레임 없음")
                        try:                                    # 조용한 구간인지, 끊긴 것인지 ping 으로 확인
                            await asyncio.wait_for(ws.ping(), timeout=10)
                            stats.idle_pings += 1
                            continue
                        except (asyncio.TimeoutError, websockets.ConnectionClosed):
                            stats.idle_reconnects += 1
                            raise ConnectionError(f"{idle_timeout:.0f}초 무응답")
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", "replace")
                    now = time.time()
                    stats.last_recv = now
                    fr = parse_frame(raw, stats.widths)
                    if fr.kind == "pingpong":
                        await ws.pong(raw.encode("utf-8"))
                        continue
                    if fr.kind == "system":
                        sub = (fr.tr_id, fr.tr_key)
                        pending.discard(sub)
                        if fr.rt_cd == "0" or "SUCCESS" in fr.msg or "ALREADY" in fr.msg:
                            stats.subscribe_ok += 1
                            ok_this_conn += 1
                        elif "MAX SUBSCRIBE" in fr.msg:
                            stats.subscribe_failed[sub] = fr.msg
                            active = [s for s in active if s != sub]
                            log(f"등록 거절(한도) {TR_NAME.get(fr.tr_id, fr.tr_id)} {fr.tr_key} — 이 종목은 뺀다")
                        else:
                            stats.subscribe_failed[sub] = fr.msg
                            stats.errors.append(f"{datetime.now():%H:%M:%S} 구독 거절 {fr.tr_id} {fr.tr_key}: {fr.rt_cd} {fr.msg}")
                            if not pending and ok_this_conn == 0:
                                need_new_key = True
                                raise ConnectionError("구독 전부 거절 — 접속키 재발급")
                        continue
                    if fr.kind == "encrypted":
                        stats.encrypted_dropped += 1
                        if stats.encrypted_dropped == 1:
                            log(f"암호화 프레임 수신({fr.tr_id}) — 복호화 미구현, 버림")
                        continue
                    if fr.kind in ("malformed", "unknown"):
                        stats.malformed += 1
                        if on_malformed:
                            on_malformed(raw)
                        continue
                    stats.frames += 1
                    if not got_data_this_conn:
                        got_data_this_conn = True
                        backoff, consecutive_fail = 2.0, 0
                    rows, bad = records_to_rows(fr, int(now * 1000))
                    stats.bad_code_rows += bad
                    if rows and not stats.alignment:
                        problems = alignment_check(rows[0])
                        stats.alignment = "OK" if not problems else "FAIL: " + ",".join(problems)
                        if problems:
                            log(f"열 정렬 점검 실패 {fr.tr_id}: {problems} — 초과 필드 위치 확인 필요")
                    for r in rows:
                        k = (fr.tr_id, r["MKSC_SHRN_ISCD"])
                        stats.records[k] = stats.records.get(k, 0) + 1
                    try:
                        on_rows(rows)
                    except OSError as exc:
                        raise StorageError(f"저장 실패: {type(exc).__name__}") from None
                try:                                               # 정상 종료: 구독 해제(최선)
                    for tr_id, code in active:
                        await ws.send(subscribe_msg(key, tr_id, code, "2"))
                except Exception:  # noqa: BLE001
                    pass
        except (StorageError, NoDataError):
            raise
        except Exception as exc:  # noqa: BLE001 — 끊김·인증·네트워크는 다시 붙는다
            if datetime.now() >= until:
                break
            disconnected_at = disconnected_at or time.time()
            consecutive_fail += 1
            stats.errors.append(_errline(exc))
            if consecutive_fail >= max_consecutive_failures:
                raise RuntimeError(f"연속 {consecutive_fail}회 연결 실패 — 포기") from None
            if consecutive_fail % 3 == 0:
                need_new_key = True
            log(f"연결 끊김({type(exc).__name__}) — {backoff:.0f}초 뒤 재연결")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
