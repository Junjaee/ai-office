from record_site import (
    parse_committees, parse_sessions, parse_meetings, filename_from_disposition,
)

TREE_CLASS2 = '''
<ul class="tree_list">
<li><div class="tit_wrap"><div class="txt">
<a href="javascript:void(0);" class="tit cmit" id="cmit_AD" data-sess="" data-th="22" data-class="2"
   data-cmit="AD" data-chk1="all" data-chk2="" data-chk3="" data-chk4="" data-str="min" data-year=>
<strong>   기획재정위원회   </strong></a>
<button type="button" class="btn_tit cmit" id="cmit_AD" data-cmit="AD" data-th="22" data-class="2">상세내용 보기</button>
</div></div></li>
<li><div class="tit_wrap"><div class="txt">
<a href="javascript:void(0);" class="tit cmit" id="cmit_AS" data-sess="" data-th="22" data-class="2"
   data-cmit="AS" data-chk1="all" data-chk2="" data-chk3="" data-chk4="" data-str="min" data-year=>
<strong> 재정경제기획위원회 </strong></a>
</div></div></li>
</ul>'''

TREE_CLASS4 = '''
<ul class="tree_list">
<li><div class="tit_wrap"><div class="txt">
<a href="javascript:void(0);" class="tit sess" data-th="22" data-class="4" data-sess="439" data-chk1="all">
<strong>제439회 ( 2026. 09. 01. ~ 2026. 12. 09. ) (정기회)</strong></a></div></div></li>
<li><div class="tit_wrap"><div class="txt">
<a href="javascript:void(0);" class="tit sess" data-th="22" data-class="4" data-sess="438" data-chk1="all">
<strong>제438회 ( 2026. 08. 02. ~ 2026. 08. 31. )</strong></a></div></div></li>
</ul>'''

SESS_CMIT = '''<li><div class="tit_wrap"><div class="txt"><a href="javascript:void(0);" class="tit sub" data-cmit="" data-th="22" data-sess="438" data-class="2" data-cmitCd="AS" data-chk1="all"><strong>제438회 (2026. 08. 02. ~ 2026. 08. 31.)</strong></a></div></div><ul class="con depth3" id="ordAS438"></ul></li><li><div class="tit_wrap"><div class="txt"><a href="javascript:void(0);" class="tit sub" data-cmit="" data-th="22" data-sess="437" data-class="2" data-cmitCd="AS" data-chk1="all"><strong>제437회 (2026. 07. 06. ~ 2026. 07. 31.)</strong></a></div></div></li>'''

SESS_CMIT_AUDIT = '''<li><div class="tit_wrap"><div class="txt"><a href="javascript:void(0);" class="tit sub" data-cmit="" data-th="22" data-sess="" data-class="5" data-cmitCd="AG" data-dt="2025" data-chk1="all"><strong>2025</strong></a></div></div><ul class="con depth3" id="ordAG2025"></ul></li><li><div class="tit_wrap"><div class="txt"><a href="javascript:void(0);" class="tit sub" data-cmit="" data-th="22" data-sess="" data-class="5" data-cmitCd="AG" data-dt="2024" data-chk1="all"><strong>2024</strong></a></div></div></li>'''

CMIT_MEETINGS = '''<li><div class="tit_wrap"><div class="txt"><a href="javascript:void(0);" data-id="57155" data-th="22" data-class="2" data-sess="438" class="tit ord_num" title="재정경제기획위원회 제1차 (2026. 08. 20.)"><strong><span span class='tit_std we' title='위원회'>위</span><span class="temp">[임시]</span> 제1차 (2026. 08. 20.) </strong></a></div><div class="btn_list"><a href="/assembly/viewer/minutes/download/hwp.do?id=57155" target='_blank' class="btn_ico"></a><a href="/assembly/viewer/minutes/download/pdf.do?id=57155" target='_blank' class="btn_ico"></a><a href="/assembly/viewer/minutes/xml.do?id=57155&type=view" target="_blank" class="btn black">회의록뷰어</a></div></div><ul class="con depth4 dot" id="item57155"></ul></li><li><div class="tit_wrap"><div class="txt"><a href="javascript:void(0);" data-id="56900" data-th="22" data-class="2" data-sess="437" class="tit ord_num" title="재정경제기획위원회 경제재정소위원회 제1차 (2026. 07. 15.)"><strong><span class='tit_std so' title='소위원회'>소</span> 경제재정소위원회 제1차 (2026. 07. 15.) </strong></a></div><div class="btn_list"><a href="/assembly/viewer/minutes/download/hwp.do?id=56900" class="btn_ico"></a><a href="/assembly/viewer/minutes/xml.do?id=56900&type=view" class="btn black">회의록뷰어</a></div></div></li>'''

PLENARY_MEETINGS = '''<li><div class="tit_wrap"><div class="txt"><a href="javascript:void(0);" class="tit ord_num" id="minutes57227" class="tit"title=""data-id="57227" data-sess="439"><strong><!-- <span class="tit_std etc" title="기타"></span> --><span class="temp">[임시]</span>제2차 (2026. 09. 03.) </strong></a></div><div class="btn_list"><a href="/assembly/viewer/minutes/download/hwp.do?id=57227" target='_blank'class="btn_ico"></a><a href="/assembly/viewer/minutes/download/pdf.do?id=57227" target='_blank'class="btn_ico"></a></div></div></li>'''


def test_parse_committees_reads_code_and_name():
    result = parse_committees(TREE_CLASS2)
    assert [(c.code, c.name) for c in result] == [("AD", "기획재정위원회"), ("AS", "재정경제기획위원회")]


def test_parse_sessions_from_tree_page_class4():
    result = parse_sessions(TREE_CLASS4)
    assert [s.key for s in result] == ["439", "438"]
    assert result[0].label.startswith("제439회")


def test_parse_sessions_from_sesscmit():
    result = parse_sessions(SESS_CMIT)
    assert [s.key for s in result] == ["438", "437"]


def test_parse_sessions_audit_years():
    result = parse_sessions(SESS_CMIT_AUDIT)
    assert [s.key for s in result] == ["2025", "2024"]


def test_parse_meetings_committee_rows():
    result = parse_meetings(CMIT_MEETINGS)
    assert len(result) == 2
    first, second = result
    assert first.id == 57155
    assert first.title == "재정경제기획위원회 제1차 (2026. 08. 20.)"
    assert first.temp is True
    assert first.has_pdf is True
    assert second.id == 56900
    assert second.temp is False
    assert second.has_pdf is False


def test_parse_meetings_plenary_row_without_title_attr():
    result = parse_meetings(PLENARY_MEETINGS)
    assert len(result) == 1
    m = result[0]
    assert m.id == 57227
    assert m.title == "제2차 (2026. 09. 03.)"
    assert m.temp is True
    assert m.has_pdf is True


def test_filename_from_disposition_decodes_utf8():
    header = 'attachment; filename="%EC%A0%9C22%EB%8C%80%EA%B5%AD%ED%9A%8C%20a.pdf";'
    assert filename_from_disposition(header) == "제22대국회 a.pdf"


def test_filename_from_disposition_missing_returns_none():
    assert filename_from_disposition(None) is None
    assert filename_from_disposition("inline") is None
