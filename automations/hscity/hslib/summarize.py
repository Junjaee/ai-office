import re


def basic_summary(body: str, limit: int = 150) -> str:
    """LLM 없이 본문에서 간단 요약 한 줄 생성: 공백 정리 후 앞부분 발췌."""
    if not body:
        return ""
    text = re.sub(r"\s+", " ", body).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"
