"""해석 저장 — 대화에서 만든 해석(JSON)을 사이트에 저장한다. 사람이 자기 PC 에서 돌린다(Actions 아님).

사용:  python save_opinion.py us ORCL --file 해석.json   (국내: kr 005930)
파일: {"verdict": "한 줄 결론", "good": [{"text": "...", "src": "재무"}], "bad": [...], "watch": ["..."]}
주가·기준일·다음 실적일은 사이트에 있는 그 종목 자료에서 채운다. 금지어(목표가·매수 추천 등)가 있으면 저장하지 않는다.
환경변수 LIVE_TOKEN 이 있으면 머리글로 보낸다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyst_publish import Site  # noqa: E402

HERE = Path(__file__).resolve().parent
FORBIDDEN = ["목표가", "매수 추천", "매도 추천", "사라", "팔아라", "강력 매수", "비중 확대", "비중 축소"]
SENTENCE_END = re.compile(r"(?<=[.!?。])\s+|\n+")


SRC = {"재무", "시세", "뉴스", "전망"}
IMPERATIVE = {"사라", "팔아라"}   # 뒤에 한글이 이어지면("사라졌다") 다른 말이라 뺀다


def _pattern(word: str) -> re.Pattern:
    """글자 사이에 공백이 얼마든 끼어도 잡는다("매수  추천"). 명령형은 뒤에 한글이 없을 때만."""
    pat = r"\s*".join(re.escape(c) for c in word.replace(" ", ""))
    return re.compile(pat + (r"(?![가-힣])" if word in IMPERATIVE else ""))


PATTERNS = [_pattern(w) for w in FORBIDDEN]


def _texts(op: dict) -> list[str]:
    """검사할 글 전부. 모양이 틀린 항목은 건너뛴다(모양 검사는 validate 가 한다)."""
    out = [op.get("verdict")]
    for key in ("good", "bad"):
        out += [x.get("text") for x in op.get(key) or [] if isinstance(x, dict)]
    out += op.get("watch") or []
    return [t for t in out if isinstance(t, str)]


def check_text(op: dict) -> list[str]:
    """금지어가 들어 있는 문장을 돌려준다(없으면 []). 글자 사이 띄어쓰기 차이는 무시한다."""
    found = []
    for text in _texts(op):
        for sentence in SENTENCE_END.split(text):
            if any(p.search(sentence) for p in PATTERNS):
                found.append(sentence.strip())
    return found


def _text_ok(v, max_len: int) -> bool:
    return isinstance(v, str) and 1 <= len(v.strip()) <= max_len


def validate(data: dict) -> str | None:
    """사이트(Worker)가 받는 모양과 같은 검사. 어긋나면 사람이 읽을 한 줄, 맞으면 None."""
    if not _text_ok(data.get("verdict"), 300):
        return "verdict(한 줄 결론)는 1~300자 글이어야 합니다."
    for key in ("good", "bad"):
        items = data.get(key)
        if not (isinstance(items, list) and 1 <= len(items) <= 6):
            return f"{key} 는 1~6개여야 합니다."
        for n, x in enumerate(items, 1):
            if not (isinstance(x, dict) and _text_ok(x.get("text"), 300)):
                return f"{key} {n}번째 항목은 text(1~300자 글)와 src 가 있는 {{ }} 모양이어야 합니다."
            if x.get("src") not in SRC:
                return f"{key} {n}번째 항목의 src 는 재무·시세·뉴스·전망 중 하나여야 합니다."
    watch = data.get("watch", [])
    if not (isinstance(watch, list) and len(watch) <= 6 and all(_text_ok(w, 200) for w in watch)):
        return "watch 는 200자 이하 글 6개까지의 목록이어야 합니다."
    return None


def _fail(msg: str, code: int = 1) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: list[str], site: Site | None = None) -> int:
    p = argparse.ArgumentParser(description="해석을 사이트에 저장한다")
    p.add_argument("market", choices=["us", "kr"])
    p.add_argument("ticker")
    p.add_argument("--file", required=True, help="해석 JSON 파일")
    args = p.parse_args(argv)
    if args.market == "kr":
        ticker = args.ticker
        if not re.fullmatch(r"[0-9][0-9A-Z]{5}", ticker):
            return _fail(f"국내 종목은 6자리 코드여야 합니다(예: 005930): {ticker}")
    else:
        ticker = args.ticker.upper()

    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _fail(f"파일을 찾을 수 없습니다: {args.file}")
    except (OSError, ValueError) as exc:   # JSON 오류도 ValueError
        return _fail(f"파일을 읽지 못했습니다(JSON 형식을 확인하세요): {exc}")
    if not isinstance(data, dict):
        return _fail("파일 맨 바깥은 { } 여야 합니다.")
    if data.get("watch") is None:
        data["watch"] = []
    problem = validate(data)
    if problem:
        return _fail(f"파일 내용을 고쳐 주세요: {problem}")
    opinion = {"verdict": data["verdict"], "good": data["good"], "bad": data["bad"], "watch": data["watch"]}

    hits = check_text(opinion)
    if hits:
        print("금지어가 들어 있어 저장하지 않았습니다. 아래 문장을 고쳐 주세요.", file=sys.stderr)
        for s in hits:
            print(f"  - {s}", file=sys.stderr)
        return 2

    if site is None:
        with open(HERE / "config.actions.yaml", encoding="utf-8") as f:
            site_url = (yaml.safe_load(f) or {})["site_url"]
        site = Site(site_url, token=os.environ.get("LIVE_TOKEN", ""))
    else:
        site_url = getattr(site, "base", "")

    try:
        doc = site.ticker(args.market, ticker).get("doc")
        rec = (doc or {}).get("rec") or {}
        if not doc or rec.get("price") is None:
            return _fail(f"사이트에 {ticker} 자료가 없습니다. 관심 종목에 넣고 다음 실행 뒤에 다시 하세요.")
        opinion.update(price=rec["price"], as_of=doc.get("as_of"), next_earn=rec.get("next_earn"))
        oid = site.opinion(args.market, ticker, opinion)
    except Exception as exc:  # noqa: BLE001 - 사람이 읽을 한 줄로 바꿔 끝낸다
        return _fail(f"사이트와 통신하지 못했습니다: {type(exc).__name__}: {exc}")
    print(f"저장했습니다: {oid}")
    print(f"{site_url}/home/stock/{args.market}/{ticker}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
