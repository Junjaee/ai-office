"""universe_kr.txt 검사 — 코드 모양·거래소·중복·개수 (코드 모양은 Worker 와 같아야 해서 어긋나면 첫 실행이 저장에서 실패한다)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

UNIVERSE = Path(__file__).resolve().parent.parent / "universe_kr.txt"


def _rows():
    return [l.partition("#")[0].split() for l in UNIVERSE.read_text(encoding="utf-8").splitlines() if l.partition("#")[0].strip()]


def test_universe_kr_shape():
    rows = _rows()
    codes = [r[0] for r in rows]
    assert all(re.fullmatch(r"[0-9][0-9A-Z]{5}", c) for c in codes), [c for c in codes if not re.fullmatch(r"[0-9][0-9A-Z]{5}", c)]
    assert all(len(r) == 2 and r[1] in ("KS", "KQ") for r in rows)
    assert len(codes) == len(set(codes))
    assert 300 <= len(codes) <= 400
