import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kis_client as kc  # noqa: E402
import record  # noqa: E402


def _frame(tr_id, n, width, code="005930", hour="135800"):
    recs = []
    for k in range(n):
        f = [code, f"{hour[:4]}{k:02d}"] + [str(100 + i) for i in range(width - 2)]
        recs.append("^".join(f))
    return f"0|{tr_id}|{n:03d}|" + "^".join(recs)


def test_parse_data_frame_uses_observed_width_and_learns_it():
    widths = {}
    fr = kc.parse_frame(_frame("H0STASP0", 1, 63), widths)
    assert fr.kind == "data" and len(fr.records) == 1 and len(fr.records[0]) == 63 and widths["H0STASP0"] == 63
    fr = kc.parse_frame(_frame("H0STCNT0", 3, 47), widths)
    assert len(fr.records) == 3 and all(len(r) == 47 for r in fr.records)
    rows, bad = kc.records_to_rows(fr, 1700000000000)
    assert bad == 0 and rows[0]["MKSC_SHRN_ISCD"] == "005930" and rows[0]["EXTRA1"] == "144" and rows[2]["STCK_CNTG_HOUR"] == "135802" and rows[2]["seq"] == 2
    # 폭이 바뀐 프레임·건수와 필드가 안 나눠지는 프레임은 malformed
    assert kc.parse_frame(_frame("H0STCNT0", 1, 50), widths).kind == "malformed"
    bad_frame = "0|H0STCNT0|002|" + "^".join(str(i) for i in range(141))
    assert kc.parse_frame(bad_frame, widths).kind == "malformed"
    assert kc.parse_frame("1|H0STASP0|001|AbC+dEf/GhI==").kind == "encrypted"


def test_records_to_rows_rejects_bad_codes():
    fr = kc.Frame("data", tr_id="H0STCNT0", records=[["112.06"] + ["1"] * 46, ["005930"] + ["1"] * 46])
    rows, bad = kc.records_to_rows(fr, 1)
    assert bad == 1 and len(rows) == 1 and rows[0]["MKSC_SHRN_ISCD"] == "005930"


def test_columns_for_names_extras_and_truncates():
    cols = kc.columns_for("H0STASP0", 63)
    assert cols[:2] == ["MKSC_SHRN_ISCD", "BSOP_HOUR"] and cols[-4:] == ["EXTRA1", "EXTRA2", "EXTRA3", "EXTRA4"]
    assert len(kc.columns_for("H0STCNT0", 40)) == 40


def test_parse_system_and_pingpong():
    ok = json.dumps({"header": {"tr_id": "H0STASP0", "tr_key": "005930"}, "body": {"rt_cd": "0", "msg1": "SUBSCRIBE SUCCESS"}})
    fr = kc.parse_frame(ok); assert fr.kind == "system" and fr.rt_cd == "0" and fr.tr_key == "005930" and "SUCCESS" in fr.msg
    bad = json.dumps({"header": {"tr_id": "H0STASP0", "tr_key": "000660"}, "body": {"rt_cd": "1", "msg1": "MAX SUBSCRIBE OVER"}})
    fr = kc.parse_frame(bad); assert fr.rt_cd == "1" and "MAX SUBSCRIBE" in fr.msg
    weird = json.dumps({"header": {"tr_id": "H0STASP0", "tr_key": "000660"}, "body": {"rt_cd": "1", "msg1": "키:<script>\"x\"</script>"}})
    assert "<" not in kc.parse_frame(weird).msg
    pp = json.dumps({"header": {"tr_id": "PINGPONG", "datetime": "20260928135800"}})
    assert kc.parse_frame(pp).kind == "pingpong"
    assert kc.parse_frame("garbage").kind == "unknown" and kc.parse_frame("").kind == "unknown"


def test_alignment_check():
    row = {"tr_id": "H0STASP0", "ASKP1": "274000", "BIDP1": "273500", "BSOP_HOUR": "140444", "TOTAL_ASKP_RSQN": "55"}
    row.update({f"ASKP_RSQN{i}": "5" for i in range(1, 11)}); row["ASKP_RSQN1"] = "10"
    assert kc.alignment_check(row) == []
    row["ASKP1"] = "100"
    assert "ASKP1>BIDP1" in kc.alignment_check(row)


def test_subscribe_msg_shape():
    m = json.loads(kc.subscribe_msg("KEY", "H0STASP0", "005930"))
    assert m["header"]["approval_key"] == "KEY" and m["header"]["tr_type"] == "1" and m["header"]["custtype"] == "P"
    assert m["body"]["input"] == {"tr_id": "H0STASP0", "tr_key": "005930"}


def test_build_subs_and_max_codes():
    assert record.build_subs(["005930", "000660", "035420", "005380"], "both") == [("H0STASP0", "005930"), ("H0STCNT0", "005930"), ("H0STASP0", "000660")]
    assert record.build_subs(["005930", "000660", "035420", "005380"], "asp") == [("H0STASP0", "005930"), ("H0STASP0", "000660"), ("H0STASP0", "035420")]
    assert record.max_codes("both") == 2 and record.max_codes("asp") == 3


def test_daystore_writes_csv_and_parquet_all_strings(tmp_path):
    st = record.DayStore(tmp_path / "run_1")
    fr = kc.parse_frame(_frame("H0STCNT0", 2, 47, hour="090000"))
    rows, _ = kc.records_to_rows(fr, 1700000000000)
    st.write(rows); st.malformed("0|X|abc"); st.flush(); st.close()
    p = tmp_path / "run_1" / "H0STCNT0_005930.csv"
    lines = p.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("recv_ms,seq,MKSC_SHRN_ISCD,STCK_CNTG_HOUR") and lines[0].endswith("EXTRA1") and len(lines) == 3
    n, failed = record.csv_to_parquet(tmp_path, log_fn=lambda m: None)
    assert n == 1 and not failed and not p.exists()
    import pyarrow.parquet as pq
    t = pq.read_table(tmp_path / "run_1" / "H0STCNT0_005930.parquet")
    assert t.num_rows == 2 and all(str(f.type) == "string" for f in t.schema)
    assert t.column("STCK_CNTG_HOUR")[0].as_py() == "090000"          # 앞자리 0 보존
    assert (tmp_path / "run_1" / "bad_frames.log").read_text(encoding="utf-8").strip().endswith("0|X|abc")


def test_lock_blocks_other_live_process_and_ignores_dead(tmp_path):
    import os
    import pytest
    p = tmp_path / "record.lock"
    p.write_text(str(os.getppid()))                    # 살아 있는 다른 프로세스(부모)가 잡은 잠금
    with pytest.raises(SystemExit):
        with record.Lock(p):
            pass
    p.write_text("999999")                             # 죽은 PID 는 무시하고 이어받는다
    with record.Lock(p):
        assert p.read_text() == str(os.getpid())
    assert not p.exists()


def test_watchlist_rejects_octal_and_bad_codes(tmp_path):
    import kis_pick
    cfg = tmp_path / "c.yaml"
    cfg.write_text('kis_watchlist: ["005930", "000660"]\n', encoding="utf-8")
    assert kis_pick.watchlist(cfg) == ["005930", "000660"]
    cfg.write_text("kis_watchlist: [005930, 000660]\n", encoding="utf-8")          # 따옴표 없음 → BaseLoader 로 문자열 그대로
    assert kis_pick.watchlist(cfg) == ["005930", "000660"]
    cfg.write_text('kis_watchlist: ["5930"]\n', encoding="utf-8")
    import pytest
    with pytest.raises(SystemExit):
        kis_pick.watchlist(cfg)


def test_rest_session_retries_and_day_minutes(monkeypatch, tmp_path):
    import kis_rest as kr
    monkeypatch.setenv("KIS_APP_KEY", "k" * 36); monkeypatch.setenv("KIS_APP_SECRET", "s" * 180)
    calls = {"n": 0}

    class R:
        def __init__(self, status, body): self.status_code = status; self._b = body
        def json(self): return self._b

    class Http:
        def post(self, url, **kw): return R(200, {"access_token": "T", "access_token_token_expired": "2999-01-01 00:00:00"})
        def get(self, url, headers=None, params=None, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return R(500, {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "초당 거래건수를 초과하였습니다."})
            if params["FID_INPUT_HOUR_1"] == "153000":
                rows = [{"stck_bsop_date": params["FID_INPUT_DATE_1"], "stck_cntg_hour": f"{(13*60+21+i)//60:02d}{(13*60+21+i)%60:02d}00", "stck_prpr": "1", "stck_oprc": "1", "stck_hgpr": "1", "stck_lwpr": "1", "cntg_vol": "1", "acml_tr_pbmn": "1"} for i in range(120)]
            else:
                rows = [{"stck_bsop_date": params["FID_INPUT_DATE_1"], "stck_cntg_hour": "090000", "stck_prpr": "1", "stck_oprc": "1", "stck_hgpr": "1", "stck_lwpr": "1", "cntg_vol": "1", "acml_tr_pbmn": "1"}]
            return R(200, {"rt_cd": "0", "msg_cd": "MCA00000", "output2": rows, "output1": {"askp1": "1"}})

    monkeypatch.setattr(kr.time, "sleep", lambda s: None)
    ses = kr.Session(interval=0, log=lambda m: None, token_file=tmp_path / "token.json", http=Http())
    rows = ses.day_minutes("005930", "20260923")
    assert ses.rate_hits == 1 and ses.retries == 1
    assert rows and rows[0]["stck_cntg_hour"] == "090000" and len(rows) == 121 and rows[-1]["stck_cntg_hour"] >= "150000"
    assert (tmp_path / "token.json").exists()
