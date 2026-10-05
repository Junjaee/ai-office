"""해석 저장 — 대화에서 만든 해석(JSON)을 사이트에 저장한다. 사람이 자기 PC 에서 돌린다(Actions 아님).

사용:  python save_opinion.py us ORCL --file 해석.json
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


def _texts(op: dict) -> list[str]:
    return ([op.get("verdict") or ""] + [x.get("text") or "" for x in (op.get("good") or []) + (op.get("bad") or [])]
            + list(op.get("watch") or []))


def check_text(op: dict) -> list[str]:
    """금지어가 들어 있는 문장을 돌려준다(없으면 []). 띄어쓰기 차이는 무시한다."""
    found = []
    for text in _texts(op):
        for sentence in SENTENCE_END.split(text):
            flat = sentence.replace(" ", "")
            if any(w.replace(" ", "") in flat for w in FORBIDDEN):
                found.append(sentence.strip())
    return found


def _fail(msg: str, code: int = 1) -> int:
    print(msg, file=sys.stderr)
    return code


def main(argv: list[str], site: Site | None = None) -> int:
    p = argparse.ArgumentParser(description="해석을 사이트에 저장한다")
    p.add_argument("market", choices=["us"])
    p.add_argument("ticker")
    p.add_argument("--file", required=True, help="해석 JSON 파일")
    args = p.parse_args(argv)
    ticker = args.ticker.upper()

    try:
        data = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _fail(f"파일을 찾을 수 없습니다: {args.file}")
    except (OSError, ValueError) as exc:   # JSON 오류도 ValueError
        return _fail(f"파일을 읽지 못했습니다(JSON 형식을 확인하세요): {exc}")
    if not isinstance(data, dict):
        return _fail("파일 맨 바깥은 { } 여야 합니다.")
    verdict = data.get("verdict")
    if not (isinstance(verdict, str) and verdict.strip()):
        return _fail("파일에 verdict(한 줄 결론)가 없습니다.")
    for key in ("good", "bad"):
        if not (isinstance(data.get(key), list) and data[key]):
            return _fail(f"파일에 {key} 항목이 없습니다(1개 이상 필요).")
    opinion = {"verdict": verdict, "good": data["good"], "bad": data["bad"], "watch": data.get("watch") or []}

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
