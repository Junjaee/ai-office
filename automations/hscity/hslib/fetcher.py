import time
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) hscity-dongtan-notify/1.0"


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA})
    return s


def get_with_retry(session, url, retries=3, backoff=1.0, timeout=20):
    last = None
    for attempt in range(retries):
        try:
            return session.get(url, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            last = e
            if backoff:
                time.sleep(backoff * (attempt + 1))
    raise last
