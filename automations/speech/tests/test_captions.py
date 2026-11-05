"""자막 수신기의 순수 부분 — AI 자막 수정본 걸러내기, 기록(jsonl)·재생. 네트워크 없음."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from captions import Caption, FinalFilter, record_line, replay  # noqa: E402

KST = timezone(timedelta(hours=9))


def test_final_filter_passes_each_segment_once():
    f = FinalFilter()
    a = Caption(1, "가", False, 7)
    b = Caption(2, "가나", True, 7)
    c = Caption(3, "가나다", True, 7)
    assert f.accept(a) is None
    assert f.accept(b) == b
    assert f.accept(c) is None


def test_final_filter_passes_stt_always():
    f = FinalFilter()
    assert f.accept(Caption(1, "한 줄")) is not None
    assert f.accept(Caption(2, "또 한 줄")) is not None


def test_replay_reads_recording_format(tmp_path):
    # 2026-11-05 녹음 파일과 같은 줄 모양. info/tick 줄은 무시, final 아닌 ai 줄은 그대로 Caption(final=False)
    p = tmp_path / "rec.jsonl"
    p.write_text("\n".join([
        json.dumps({"t": "2026-11-05T20:34:42", "kind": "info", "text": "채널 예결위"}, ensure_ascii=False),
        json.dumps({"t": "2026-11-05T20:34:42", "kind": "ai", "segment": 123, "final": True, "scd": True,
                    "text": "개혁신당 이준석 위원님 질의하여 주십시오"}, ensure_ascii=False),
        json.dumps({"t": "2026-11-05T20:34:45", "kind": "ai", "segment": 124, "final": False, "scd": False, "text": "홍지선"}, ensure_ascii=False),
        json.dumps({"t": "2026-11-05T20:35:00", "kind": "tick", "text": "3건"}, ensure_ascii=False),
        json.dumps({"t": "2026-11-05T20:35:01", "kind": "stt", "text": "속기 한 줄"}, ensure_ascii=False),
    ]) + "\n", encoding="utf-8")
    rows = list(replay(str(p)))
    assert [r.text for r in rows] == ["개혁신당 이준석 위원님 질의하여 주십시오", "홍지선", "속기 한 줄"]
    assert rows[0].segment == 123 and rows[0].final is True
    assert rows[1].final is False
    assert rows[2].segment is None and rows[2].final is True
    assert rows[0].at == datetime(2026, 11, 5, 20, 34, 42, tzinfo=KST).timestamp()


def test_record_then_replay_roundtrip(tmp_path):
    p = tmp_path / "rec.jsonl"
    c = Caption(datetime(2026, 11, 5, 21, 0, 0, tzinfo=KST).timestamp(), "질의 시작", True, 5)
    with p.open("a", encoding="utf-8") as fp:
        record_line(fp, c, "ai")
    line = json.loads(p.read_text(encoding="utf-8").strip())
    assert line["t"] == "2026-11-05T21:00:00" and line["kind"] == "ai" and line["segment"] == 5
    assert list(replay(str(p))) == [c]
