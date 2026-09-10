"""자동화 예외 → 화면(AI 오피스)에 보여줄 한국어 한 줄.

사용:
    from errors import MissingGoogleToken, to_korean
    try: ...
    except Exception as exc:
        report(..., ok=False, summary=to_korean(exc), log_lines=[f"{type(exc).__name__}: {exc}"[:300]])
"""
from __future__ import annotations

import errno

try:
    import requests  # noqa: F401
    _REQ_CONN = (requests.exceptions.ConnectionError, requests.exceptions.Timeout)
except ImportError:  # pragma: no cover - requests 없는 환경
    _REQ_CONN = ()

MSG_SITE = "국회 사이트에 연결할 수 없어요"
MSG_NEWS = "뉴스 목록을 받아오지 못했어요"
MSG_GOOGLE = "구글 드라이브 인증이 없거나 만료됐어요"
MSG_DISK = "저장 공간이 부족해요"
MSG_OTHER = "실행 중 문제가 생겼어요"


class MissingGoogleToken(Exception):
    """GOOGLE_REFRESH_TOKEN 환경변수가 비어 있다 (드라이브 저장소를 쓸 수 없음)."""


def _class_names(exc: BaseException) -> set[str]:
    return {c.__name__ for c in type(exc).__mro__}


def to_korean(exc: BaseException) -> str:
    """알려진 예외를 한국어 한 줄로. 모르는 예외는 '실행 중 문제가 생겼어요'."""
    names = _class_names(exc)
    msg = str(exc)
    # 구글 인증: 토큰 없음 / google.auth.exceptions.RefreshError (google-auth 미설치여도 이름으로 판별)
    if isinstance(exc, MissingGoogleToken) or "RefreshError" in names:
        return MSG_GOOGLE
    # 디스크 부족
    if (isinstance(exc, OSError) and exc.errno == errno.ENOSPC) or "디스크 여유" in msg:
        return MSG_DISK
    # 뉴스 RSS: google_news 가 재시도 끝에 던지는 RuntimeError("뉴스 요청 실패 ...") — 국회 사이트보다 먼저 본다
    if isinstance(exc, RuntimeError) and "뉴스 요청 실패" in msg:
        return MSG_NEWS
    # 국회 사이트 연결: requests 연결/타임아웃, 또는 record_site가 재시도 끝에 던지는 RuntimeError("요청 실패 ...")
    if _REQ_CONN and isinstance(exc, _REQ_CONN):
        return MSG_SITE
    if isinstance(exc, RuntimeError) and "요청 실패" in msg:
        return MSG_SITE
    return MSG_OTHER
