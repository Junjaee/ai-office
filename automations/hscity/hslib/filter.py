import re
from dataclasses import dataclass


@dataclass
class MatchResult:
    included: bool
    is_star: bool = False
    is_citywide: bool = False


def _kw_match(text: str, words: list[str]) -> bool:
    """키워드가 앞에 한글이 붙은 더 긴 단어의 일부로 들어간 경우(예: '반송동' 속의 '송동')를
    오탐으로 잡지 않도록, 키워드 바로 앞에 한글이 오면 매칭에서 제외한다."""
    for w in words:
        if re.search(r"(?<![가-힣])" + re.escape(w), text):
            return True
    return False


def _phrase_match(text: str, phrases: list[str]) -> bool:
    return any(p in text for p in phrases)


def match(title: str, body: str, filt: dict) -> MatchResult:
    text = f"{title}\n{body}"
    has_include = _kw_match(text, filt["include_keywords"])
    has_citywide = _phrase_match(text, filt.get("citywide_markers", []))

    if not has_include and not has_citywide:
        return MatchResult(included=False)

    is_star = _kw_match(text, filt.get("star_keywords", []))
    return MatchResult(included=True, is_star=is_star, is_citywide=has_citywide and not has_include)
