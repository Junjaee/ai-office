import errno

import requests

from errors import MSG_DISK, MSG_GOOGLE, MSG_OTHER, MSG_SITE, MissingGoogleToken, to_korean


def test_requests_connection_and_timeout_map_to_site():
    assert to_korean(requests.exceptions.ConnectionError("boom")) == MSG_SITE
    assert to_korean(requests.exceptions.Timeout("slow")) == MSG_SITE
    assert to_korean(requests.exceptions.ConnectTimeout("slow")) == MSG_SITE      # Timeout 하위 클래스


def test_record_site_runtime_error_maps_to_site():
    assert to_korean(RuntimeError("요청 실패 GET https://likms.assembly.go.kr/x: ConnectionError")) == MSG_SITE
    assert to_korean(RuntimeError("PDF가 아닌 응답")) == MSG_OTHER


def test_google_refresh_error_and_missing_token():
    from google.auth.exceptions import RefreshError
    assert to_korean(RefreshError("invalid_grant")) == MSG_GOOGLE
    assert to_korean(MissingGoogleToken()) == MSG_GOOGLE

    class RefreshError(Exception):  # noqa: F811 - google-auth가 없을 때 이름으로 판별
        pass
    assert to_korean(RefreshError("x")) == MSG_GOOGLE


def test_disk_full():
    assert to_korean(OSError(errno.ENOSPC, "No space left on device")) == MSG_DISK
    assert to_korean(RuntimeError("디스크 여유 1.2GB 미만, 중단")) == MSG_DISK
    assert to_korean(OSError(errno.EACCES, "denied")) == MSG_OTHER


def test_unknown_exception():
    assert to_korean(ValueError("x")) == MSG_OTHER
    assert to_korean(KeyError("drive_folder_id")) == MSG_OTHER


def test_calendar_and_telegram_messages():
    from errors import MSG_CALENDAR, MSG_TELEGRAM, MSG_TELEGRAM_SETUP
    assert to_korean(RuntimeError("캘린더 읽기 실패: HTTP 403")) == MSG_CALENDAR
    assert to_korean(RuntimeError("텔레그램 전송 실패: Forbidden")) == MSG_TELEGRAM
    assert to_korean(RuntimeError("텔레그램 설정 없음: TELEGRAM_CHAT_ID")) == MSG_TELEGRAM_SETUP
