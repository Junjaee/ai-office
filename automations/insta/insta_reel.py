"""말하는 대본 → 자막 싱크 릴스 (릴스 v2, 2026-09-14).

v1(insta_slideshow)은 카드 글을 그대로 읽어 부자연스러웠다(사용자 지적 → 중지). v2 는 한국 정보 릴스의 실제 방식을 따른다
(research/릴스_나레이션_리서치_2026-09-14.md):
1) 편집장이 카드와 별도로 **말하는 대본**을 쓴다 — 인기 정보 쇼츠 실제 대본을 분석한 규칙(합쇼체, 결론+숫자 훅 → 공감 → 번호 → 조건 → 공유 유도), 35~55초. (script_prompt, REEL_SCRIPT_SCHEMA)
2) 대본을 구간별로 TTS 로 읽고 단어 시각을 받는다(엣지 음성은 단어 시각을 주고, 없으면 글자 수로 나눠 추정).
3) 장면 = 테마 배경(카드 사진이 있으면 흐리게 깔고 가운데 크게) + 큰 강조 문구. 자막 = 지금 말하는 구절이 1초 남짓마다 바뀌고 강조어는 색.
   Pillow 로 프레임을 만들고 ffmpeg concat 으로 잇는다(프레임이 수십 장뿐이라 빠르다).
4) 배경음악(선택): 코드로 만든 저작권 없는 잔잔한 루프(make_bgm)를 목소리 아래 깐다. 말하는 동안 자동으로 줄어든다.
   인스타 음악 라이브러리(유행 음악)는 API 게시에서 쓸 수 없다 — 소리는 영상 파일 안에 넣어야 한다.
목소리 없이(voice=None) 만들면 '음악 + 큰 자막' 릴스가 된다(한국 AI 계정 인기 릴스의 주류 형태).
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
W, H = 1080, 1920
FPS = 30
GAP = 0.25                      # 구간 사이 쉼(초)
FONT_WOFF2 = HERE / "fonts" / "PretendardVariable.woff2"

REEL_SCRIPT_SCHEMA = {
    "type": "object",
    "required": ["hook", "segments", "cta"],
    "properties": {
        "hook": {"type": "object", "required": ["say", "big"],
                 "properties": {"say": {"type": "string", "maxLength": 70}, "big": {"type": "string", "maxLength": 26}}},
        "segments": {"type": "array", "minItems": 3, "maxItems": 5,
                     "items": {"type": "object", "required": ["say", "big"],
                               "properties": {"say": {"type": "string", "maxLength": 170}, "big": {"type": "string", "maxLength": 22},
                                              "card": {"type": "integer"}, "keywords": {"type": "array", "items": {"type": "string"}}}}},
        "cta": {"type": "object", "required": ["say", "big"],
                "properties": {"say": {"type": "string", "maxLength": 120}, "big": {"type": "string", "maxLength": 22}}},
    },
}


# ───────────────────────── 1) 말하는 대본 ─────────────────────────

def script_prompt(profile_name: str, audience: str, article: dict, slides: list[dict], dm_keyword: str = "") -> tuple[str, str]:
    # 말투·구조는 조회수 100만~800만 한국 정보 쇼츠 6개의 실제 나레이션을 받아 적어 분석한 것(research/릴스_대본_리서치_2026-09-14.md).
    # 공통점: 합쇼체로 짧게 끊어 단정 → 결론+숫자+대상 훅 → 공감·문제 → 반전 → '첫 번째·두 번째' 번호 → 손해·조건 → 공유 유도.
    system = (f"당신은 인스타그램 정보 계정 '{profile_name}'의 릴스 나레이션 작가입니다. 독자: {audience}\n"
              "카드뉴스로 쓴 기사를 **귀로 듣는 35~55초 릴스 나레이션**으로 다시 씁니다. 카드 문장을 그대로 옮기지 않습니다.\n"
              "말투(한국 인기 정보 쇼츠의 실제 말투):\n"
              "- 합쇼체로 짧고 단정하게: '~습니다', '~입니다', '~하세요'. 한 문장 8~25자. 명사로 끊는 문장도 좋다('신청은 단 한 번.').\n"
              "- 친구 말투(~거든요/~더라고요/~잖아요)와 설명조 긴 문장은 쓰지 않는다. 궁금증은 질문 한 번('~일까요?', '~알고 계셨나요?')으로.\n"
              "- 핵심 숫자는 두 번 말한다(훅에서 한 번, 설명에서 한 번). 숫자는 소리 내 읽기 쉽게('1,000원' → '천 원', '47%' → '47퍼센트').\n"
              "- 괄호·영문 병기·가운뎃점·슬래시·이모지 금지(예: '제미나이(Gemini)' → '제미나이'). 단축키는 'Alt 키랑 스페이스바'처럼 말로.\n"
              "- 사실은 기사 안의 것만. '속보' 같은 거짓 긴박감, 정답을 숨기는 낚시('화면 두 번 누르면 공개')는 금지 — 인스타는 참여 유도 낚시를 노출에서 뺀다.\n"
              "- 번역투 금지(영어 자료를 옮길 때 특히): '관련이 있었다·연관됐다'는 '~할수록 ~했다'로 풀고, "
              "'~는 다른 이야기를 한다', '~ 자신의', '~ 단위로 봐야', '개인 ~' 같은 직역과 '주 양육자' 같은 서류 말투를 쓰지 않는다. "
              "소리 내어 읽었을 때 한국 사람이 실제로 하는 말이어야 한다. 내용·숫자는 바꾸지 않는다.\n"
              "- **보고서·통계 말투 금지(2026-09-16 사용자 지적)**: '유행 기준의 네 배입니다'·'~로 나타났습니다'·'~가 확인되었습니다' 같은 자료 문장을 그대로 읽지 않는다. "
              "귀로 듣는 말로 바꾼다('9월인데 벌써 유행주의보가 내렸습니다'). 명사만 늘어놓는 문장, '첫째·둘째·셋째'를 습관처럼 붙이는 목록체도 쓰지 않는다(정말 순서가 중요할 때만). "
              "다 쓰고 나서 한 문장씩 소리 내어 읽어 보고, 혀에 걸리는 곳은 고친다.\n"
              "구조:\n"
              "- hook: **첫 문장이 전부다(사용자 지시 2026-09-16)** — 첫 단어부터 멈칫하게 만들고, 이 한 문장만 듣고도 계속 보게 해야 한다. "
              "인사·자기소개·'오늘은 ~에 대해 알아보겠습니다' 같은 예고·배경 설명으로 시작하지 않는다. 결론+숫자+대상을 한 문장에(15~28자, 첫 3초). "
              "잘 되는 형: 내 얘기 같은 상황('어젯밤 아이가 열이 났다면'), 통념 뒤집기('~가 아니었습니다'), 손해 경고('이번 주를 넘기면 늦습니다'), 놀라운 숫자('작년의 네 배입니다'). "
              "**첫 문장은 독자가 가장 아끼는 것의 이득·손해로 연다(2026-09-16 사용자 지시)** — 육아 계정이면 '내 아이', 직장인 계정이면 '내 시간·내 돈'. "
              "통계·뉴스로 시작하면 남의 일처럼 들리므로, 숫자는 버리지 말고 바로 다음 구간에서 근거로 받친다(예: 훅 '아이 독감은 치료보다 예방이 훨씬 쉽습니다' → 다음 구간 '9월인데 벌써 유행 기준의 네 배입니다'). "
              "제목을 그대로 읽지 않는다.\n"
              "- segments 3~5개(각 1~3문장): ① 공감·문제 한두 문장('요즘 ~죠. 그런데 대부분 모르고 지나갑니다.') "
              "② 반전·핵심('하지만 이번엔 다릅니다.') ③ '첫 번째', '두 번째'처럼 번호를 붙여 방법·혜택을 하나씩, 구체적인 숫자·순서로 "
              "④ 조건·손해 한 문장('단, ~는 안 됩니다' / '이거 안 하면 ~ 손해입니다'). "
              "big 은 그 구간 화면에 크게 뜰 8~14자 요약, keywords 는 자막에서 색으로 강조할 단어 1~2개, "
              "card 는 그 구간에 보여 줄 카드 번호(아래 목록에서 사진 있는 카드), 없으면 0.\n"
              "- cta: 공유 유도 + 댓글 키워드. 예 '필요한 분께 꼭 보내 주세요.' 뒤에 " +
              (f"'댓글에 '{dm_keyword}' 남기시면 ~를 DM으로 보내드립니다.' — 댓글 키워드는 반드시 '{dm_keyword}' 그대로(바꾸지 않는다)"
               if dm_keyword else "'저장해 두세요.'") + ".\n"
              "- 전체 말 분량(hook+segments+cta 의 say 합) 250~380자(35~55초).\n"
              "도구를 쓰지 말고 JSON 객체 하나만 출력합니다.")
    cards = "\n".join(f"{i}. [{s.get('kind')}] {str(s.get('title', '')).replace(chr(10), ' ')[:40]}{' (사진 있음)' if s.get('image_path') else ''}"
                      for i, s in enumerate(slides) if s.get("kind") != "cta")
    body = "\n".join(f"- {p.get('heading', '')}: {p.get('text', '')}" for p in article.get("paragraphs", []))
    user = (f"기사 제목: {article.get('title', '')}\n부제: {article.get('subtitle', '')}\n본문:\n{body}\n\n카드 목록(번호):\n{cards}\n\n"
            'JSON: {"hook": {"say": "...", "big": "..."}, "segments": [{"say": "...", "big": "...", "keywords": ["..."], "card": 2}], '
            '"cta": {"say": "...", "big": "..."}}')
    return system, user


def clean_for_speech(text: str) -> str:
    t = str(text or "")
    t = re.sub(r"\((?=[^)]*[A-Za-z])[^)]{1,30}\)", "", t)          # 영문 병기 괄호 제거
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿⭐✅️#*_`]", " ", t)
    t = t.replace("·", ", ").replace("/", " ").replace("~", "에서 ")
    return re.sub(r"\s+", " ", t).strip()


def enforce_cta(script: dict, dm_keyword: str) -> dict:
    """DM 키워드가 있으면 cta 에 그 말이 그대로 들어가게 한다(댓글→DM 자동 답장이 그 키워드로 반응하므로 모델이 바꾸면 안 된다)."""
    kw = str(dm_keyword or "").strip().strip("'\"")
    if not kw:
        return script
    cta = dict(script.get("cta") or {})
    if kw not in str(cta.get("say", "")):
        cta["say"] = f"필요한 분께 꼭 보내 주세요. 댓글에 '{kw}' 남기시면 정리한 내용을 DM으로 보내드립니다."
        cta["big"] = f"댓글에 '{kw}'"
    return {**script, "cta": cta}


def _on(color: tuple[int, int, int]) -> tuple[int, int, int]:
    """배경색 위에 읽히는 글자색(밝으면 검정, 어두우면 흰색)."""
    r, g, b = color
    return (20, 20, 20) if (0.299 * r + 0.587 * g + 0.114 * b) > 150 else (255, 255, 255)


def parts_of(script: dict) -> list[dict]:
    """대본 → 구간 목록 [{kind, say, big, keywords, card}] (hook, segments…, cta)."""
    out = [{"kind": "hook", **script["hook"]}]
    out += [{"kind": "seg", **s} for s in script.get("segments", [])]
    out.append({"kind": "cta", **script["cta"]})
    for p in out:
        p["say"] = clean_for_speech(p.get("say", ""))
        p["big"] = clean_for_speech(p.get("big", ""))
        p["keywords"] = [clean_for_speech(k) for k in (p.get("keywords") or []) if str(k).strip()]
    return out


# ───────────────────────── 2) TTS ─────────────────────────

async def _edge(text: str, voice: str, rate: str, out: Path) -> list[tuple[float, float, str]]:
    import edge_tts  # type: ignore

    words: list[tuple[float, float, str]] = []
    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    with open(out, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                s = ch["offset"] / 1e7
                words.append((s, s + ch["duration"] / 1e7, ch["text"]))
    return words


def duration_of(path: Path | str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip() or 0)


def estimate_words(text: str, dur: float) -> list[tuple[float, float, str]]:
    """단어 시각이 없을 때: 글자 수 비율로 나눈다."""
    ws = text.split()
    total = sum(len(w) for w in ws) or 1
    t, out = 0.05, []
    for w in ws:
        d = (dur - 0.1) * len(w) / total
        out.append((t, t + d, w))
        t += d
    return out


def typecast_tts(text: str, out: Path, *, voice_id: str, emotion: str = "normal", intensity: float = 1.0, tempo: float = 1.1,
                 model: str = "ssfm-v30", api_key: str = "") -> None:
    """타입캐스트 API (한국 쇼츠·릴스에서 가장 많이 쓰는 AI 성우). 환경변수 TYPECAST_API_KEY. 무료 월 1만5천 자, Lite 월 $15 20만 자."""
    import os

    import requests

    key = api_key or os.environ.get("TYPECAST_API_KEY", "").strip()
    if not key:
        raise RuntimeError("TYPECAST_API_KEY 없음")
    body = {"voice_id": voice_id, "text": text, "model": model, "language": "kor",
            "prompt": {"emotion_type": "preset", "emotion_preset": emotion, "emotion_intensity": intensity},
            "output": {"volume": 100, "audio_pitch": 0, "audio_tempo": tempo, "audio_format": "wav"}}
    r = requests.post("https://api.typecast.ai/v1/text-to-speech", headers={"X-API-KEY": key, "Content-Type": "application/json"},
                      json=body, timeout=120)
    if not r.ok:
        raise RuntimeError(f"Typecast {r.status_code}: {r.text[:200]}")
    Path(out).write_bytes(r.content)


def google_tts(text: str, out: Path, *, voice: str = "ko-KR-Chirp3-HD-Kore", rate: float = 1.1, api_key: str = "") -> None:
    """구글 클라우드 Chirp 3 HD (월 100만 자 무료). 환경변수 GOOGLE_TTS_API_KEY."""
    import base64
    import os

    import requests

    key = api_key or os.environ.get("GOOGLE_TTS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GOOGLE_TTS_API_KEY 없음")
    body = {"input": {"text": text}, "voice": {"languageCode": "ko-KR", "name": voice}, "audioConfig": {"audioEncoding": "MP3", "speakingRate": rate}}
    r = requests.post("https://texttospeech.googleapis.com/v1/text:synthesize", params={"key": key}, json=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Google TTS {r.status_code}: {r.text[:200]}")
    Path(out).write_bytes(base64.b64decode(r.json()["audioContent"]))


TIGHTEN = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
           "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse,"
           "silenceremove=stop_periods=-1:stop_duration=0.32:stop_threshold=-45dB:stop_silence=0.32")


def tighten(path) -> None:
    """유료 목소리(타입캐스트 등)의 앞뒤 무음을 자르고, 0.32초보다 긴 쉼을 0.32초로 줄인다.
    필재 샘플 실측: 말소리 길이는 그대로, 전체 약 9% 짧아짐. 쇼츠 제작 강의도 문장 사이 공백을 없애라고 권한다.
    실패하거나 원본의 60% 밑으로 줄면(말이 잘린 것) 원본을 그대로 둔다."""
    src = Path(path)
    tmp = src.with_name(src.stem + "_t" + src.suffix)
    try:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", TIGHTEN, str(tmp)], check=True, capture_output=True)
        if duration_of(tmp) >= 0.6 * duration_of(src):
            tmp.replace(src)
    except Exception:  # noqa: BLE001
        pass
    finally:
        tmp.unlink(missing_ok=True)


def speak(parts: list[dict], work: Path, *, engine: str = "edge", voice: str = "ko-KR-SunHiNeural", rate: str = "+20%",
          supertonic=None, tts_opts: dict | None = None, progress=print) -> str:
    """구간마다 음성 파일(p['audio'])과 길이(p['dur'])와 단어 시각(p['words'])을 채우고, 실제로 쓴 엔진 이름을 돌려준다.
    유료 목소리(typecast·google)가 실패하면(크레딧 소진·키 오류 등) 한 편 안에서 목소리가 섞이지 않게 전체를 엣지 음성으로 다시 만든다."""
    try:
        _speak_once(parts, work, engine=engine, voice=voice, rate=rate, supertonic=supertonic, tts_opts=tts_opts)
        return engine
    except Exception as exc:  # noqa: BLE001
        if engine not in ("typecast", "google"):
            raise
        progress(f"{engine} 목소리 실패({type(exc).__name__}: {str(exc)[:80]}) — 엣지 음성으로 대신")
        _speak_once(parts, work, engine="edge", voice="ko-KR-SunHiNeural", rate=rate)
        return "edge"


def _speak_once(parts: list[dict], work: Path, *, engine: str, voice: str, rate: str = "+20%",
                supertonic=None, tts_opts: dict | None = None) -> None:
    work.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(parts):
        mp3 = work / f"say{i:02d}.mp3"
        if engine == "edge":
            p["words"] = asyncio.run(_edge(p["say"], voice, rate, mp3))
            p["audio"] = str(mp3)
        elif engine == "supertonic" and supertonic:
            wav = work / f"say{i:02d}.wav"
            supertonic(p["say"], wav)
            p["audio"] = str(wav)
            p["words"] = []
        elif engine == "typecast":
            wav = work / f"say{i:02d}.wav"
            typecast_tts(p["say"], wav, voice_id=voice, **(tts_opts or {}))
            tighten(wav)
            p["audio"] = str(wav)
            p["words"] = []
        elif engine == "google":
            gm = work / f"say{i:02d}.mp3"
            google_tts(p["say"], gm, voice=voice or "ko-KR-Chirp3-HD-Kore", **(tts_opts or {}))
            tighten(gm)
            p["audio"] = str(gm)
            p["words"] = []
        else:
            raise ValueError(f"모르는 TTS: {engine}")
        p["dur"] = duration_of(p["audio"])
        if not p["words"]:
            p["words"] = estimate_words(p["say"], p["dur"])


def silent_timing(parts: list[dict], per_char: float = 0.085, minimum: float = 2.2) -> None:
    """목소리 없는 릴스: 읽는 속도에 맞춰 구간 길이를 정한다."""
    for p in parts:
        p["dur"] = max(minimum, len(p["say"]) * per_char + 0.6)
        p["words"] = estimate_words(p["say"], p["dur"])
        p["audio"] = ""


BOUND_WORDS = ("살", "시간", "가지", "게", "수", "것", "때", "명", "년", "개", "번", "분", "초", "점", "원", "달", "주", "배", "퍼센트", "날", "동안",
               "준", "줄", "줘")                            # 틀어 '준' 날, 해 '줄' 수 — 앞 동사와 한 덩어리


def _is_bound(word: str) -> bool:
    """앞말에 붙어 다니는 말(다섯 '살', 한 '시간', 열 '가지를', 볼 '게' …)인가."""
    w = word.strip("'\"”’(),.?!…")
    return any(w == b or (w.startswith(b) and len(w) - len(b) <= 2) for b in BOUND_WORDS)


def chunk_words(words: list[tuple[float, float, str]], max_chars: int = 13) -> list[tuple[float, float, str]]:
    """단어들을 자막 한 조각(13자 안팎, 화면에서는 두 줄까지) 단위로 묶는다 (2026-09-15 사용자 지적 반영).
    - 문장이 끝나면(. ? ! …) 반드시 끊어 새 문장이 자막 첫머리에 오게 하고, 쉼표(말 마디)에서도 끊는다
    - 숫자·꾸밈말과 뒤에 붙는 말(다섯 살, 한 시간, 볼 게) 사이에서는 끊지 않는다
    - 문장 끝 조각이 4글자 이하로 짧으면 앞 자막에 붙인다"""
    out: list[tuple[float, float, str]] = []
    cur: list[tuple[float, float, str]] = []
    sent_start = 0                                     # 지금 문장이 out 의 몇 번째 조각부터인가

    def text(ws):
        return " ".join(w for _, _, w in ws)

    def flush(end_of_sentence: bool = False):
        nonlocal cur, sent_start
        if not cur:
            return
        piece = (cur[0][0], cur[-1][1], text(cur))
        if end_of_sentence and len(out) > sent_start and len(piece[2].rstrip(".?!…,")) <= 4 \
                and len(out[-1][2]) + 1 + len(piece[2]) <= max_chars + 8:
            prev = out.pop()                           # 짧은 꼬리('끄기.')는 앞 자막에 붙인다
            piece = (prev[0], piece[1], prev[2] + " " + piece[2])
        out.append(piece)
        cur = []
        if end_of_sentence:
            sent_start = len(out)

    for s_, e_, w in words:
        n = len(text(cur + [(s_, e_, w)]))
        ends_clause = w.rstrip("'\"”’)").endswith((",", ".", "?", "!", "…"))
        if cur and n > max_chars and not (ends_clause and n <= max_chars + 4):   # 마디 끝 한 단어는 조금 넘쳐도 같은 자막에
            if _is_bound(w) and len(cur) > 1:          # '다섯 / 살' 로 갈라지지 않게 앞말을 함께 넘긴다
                carry = [cur.pop()]
                while len(cur) > 1 and _is_bound(carry[0][2]):   # '틀어 준 날' 처럼 이어진 것도 통째로
                    carry.insert(0, cur.pop())
                flush()
                cur = carry
            else:
                flush()
        cur.append((s_, e_, w))
        tail = w.rstrip("'\"”’)")
        if tail.endswith((".", "?", "!", "…")):
            flush(end_of_sentence=True)
        elif tail.endswith(",") and len(text(cur)) >= 5:
            flush()
    flush(end_of_sentence=True)
    return out


# ───────────────────────── 3) 화면 ─────────────────────────

_TTF: Path | None = None


def font(size: int, weight: int = 800):
    from PIL import ImageFont

    global _TTF
    if _TTF is None:
        _TTF = Path(__file__).resolve().parent / "fonts" / "Pretendard.ttf"
        if not _TTF.exists():
            from fontTools.ttLib import TTFont

            f = TTFont(str(FONT_WOFF2))
            f.flavor = None
            f.save(str(_TTF))
    f = ImageFont.truetype(str(_TTF), size)
    try:
        f.set_variation_by_axes([weight])
    except Exception:  # noqa: BLE001
        pass
    return f


def wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        cand = (cur + " " + w).strip()
        if draw.textlength(cand, font=fnt) <= max_w:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        cur = w
        while draw.textlength(cur, font=fnt) > max_w and len(cur) > 1:       # 한 단어가 너무 길면 글자로 자른다
            k = len(cur)
            while k > 1 and draw.textlength(cur[:k], font=fnt) > max_w:
                k -= 1
            lines.append(cur[:k])
            cur = cur[k:]
    if cur:
        lines.append(cur)
    return lines


def _hex(c: str, default=(255, 255, 255)) -> tuple[int, int, int]:
    c = str(c or "").lstrip("#")
    try:
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return default


def scene(part: dict, theme: dict, *, visual: str = "", brand: str = "AI TIPS", idx: int = 0, total: int = 1):
    """장면 바탕(자막 없음) 이미지."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

    bg, fg, accent = _hex(theme.get("bg", "#15171c"), (21, 23, 28)), _hex(theme.get("fg", "#f5f6f8")), _hex(theme.get("accent", "#f2b544"), (242, 181, 68))
    img = Image.new("RGB", (W, H), bg)
    vis = None
    if visual and Path(visual).exists():
        vis = Image.open(visual).convert("RGB")
        cover = vis.copy()
        r = max(W / cover.width, H / cover.height)
        cover = cover.resize((int(cover.width * r) + 1, int(cover.height * r) + 1)).crop((0, 0, W, H))
        cover = ImageEnhance.Brightness(cover.filter(ImageFilter.GaussianBlur(38))).enhance(0.38)
        img.paste(cover, (0, 0))
    if vis:
        fg = (255, 255, 255)                           # 흐린 사진 위에는 밝은 테마여도 흰 글씨
    else:                                              # 사진이 없으면 강조색이 은은하게 번지는 배경 (평평한 검은 화면 방지, 2026-09-15)
        mix = tuple(int(bg[i] * 0.55 + accent[i] * 0.45) for i in range(3))
        ImageDraw.Draw(img).ellipse((W // 2 - 560, 520, W // 2 + 560, 1400), fill=mix)
        img = img.filter(ImageFilter.GaussianBlur(170))
    d = ImageDraw.Draw(img)
    # 브랜드 알약 + 진행 표시
    fb = font(34, 800)
    tw = d.textlength(brand, font=fb)
    d.rounded_rectangle((70, 210, 70 + tw + 48, 270), radius=30, fill=accent)
    d.text((70 + 24, 240), brand, font=fb, fill=_on(accent), anchor="lm")
    for k in range(total):
        x = 1010 - (total - 1 - k) * 26
        d.rounded_rectangle((x - (14 if k == idx else 5), 236, x + 5, 245), radius=5, fill=accent if k == idx else (120, 120, 120))
    # 큰 문구
    big = part.get("big") or ""
    if part["kind"] == "hook":                          # 첫 화면 = 표지: 사진은 흐린 배경으로만, 가운데 큰 글씨
        fnt = font(112, 900)
        lines = wrap(d, big, fnt, 930)[:3]
        y = 760 - len(lines) * 66
        for ln in lines:
            d.text((W // 2, y), ln, font=fnt, fill=fg, anchor="mt")
            y += 134
        d.rectangle((W // 2 - 90, y + 20, W // 2 + 90, y + 30), fill=accent)
    elif not vis:                                       # 사진 없는 장면: 큰 문구를 화면 가운데에 (빈 가운데 방지)
        fnt = font(104, 900)
        lines = wrap(d, big, fnt, 940)[:3]
        y = 800 - len(lines) * 62
        for ln in lines:
            d.text((W // 2, y), ln, font=fnt, fill=fg, anchor="mt")
            y += 124
        d.rectangle((W // 2 - 70, y + 18, W // 2 + 70, y + 27), fill=accent)
    else:
        fnt = font(92 if part["kind"] != "cta" else 88, 900)
        lines = wrap(d, big, fnt, 940)[:2]
        y = 320
        for ln in lines:
            d.text((70, y), ln, font=fnt, fill=fg, anchor="lt", stroke_width=0)
            y += 112
        if vis:
            box_w, box_h, top = 940, 700, max(y + 40, 560)
            v = vis.copy()
            r = min(box_w / v.width, box_h / v.height)
            v = v.resize((max(1, int(v.width * r)), max(1, int(v.height * r))))
            mask = Image.new("L", v.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, v.width, v.height), radius=28, fill=255)
            img.paste(v, ((W - v.width) // 2, top + (box_h - v.height) // 2), mask)
    return img


def _dims(path) -> tuple[int, int]:
    """영상 가로·세로 픽셀 (ffprobe). 모르면 16:9 로 본다."""
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        w, h = (int(x) for x in r.stdout.strip().split(",")[:2])
        return w, h
    except ValueError:
        return 16, 9


def video_chain(w: int, h: int) -> str:
    """원본 영상 → [base] 필터. 세로 원본(9:16 쪽)은 화면 전체를 선명하게 채우고(가운데 작은 띠로 줄지 않게, 2026-09-15 샘플 확인),
    가로·정사각 원본은 흐린 원본으로 전체를 채운 뒤 가운데(600~1320) 상자에 선명한 원본을 넣는다."""
    if h >= w * 1.3:
        return "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[base];"
    return ("[0:v]split=2[va][vb];[va]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=24:2,"
            "eq=brightness=-0.28[bg];[vb]scale=1000:720:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:600+(720-h)/2,setsar=1[base];")


def overlay_scene(part: dict, theme: dict, *, brand: str = "AI TIPS", idx: int = 0, total: int = 1, credit: str = "", clean: bool = True):
    """영상 해설형 릴스의 글자 층(투명 바탕, 2026-09-15 사용자 결정 '해설형 재가공'): 위아래 어둠 띠 + 브랜드·진행 표시 + 큰 문구 + 출처.
    가운데(600~1320)는 비워 두어 아래 깔린 원본 영상이 보이게 한다."""
    from PIL import Image, ImageDraw

    accent = _hex(theme.get("accent", "#f2b544"), (242, 181, 68))
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if clean:                                          # 2026-09-15 사용자 지시: 영상 위에는 자막만 (띠·제목·브랜드 알약·진행 점·AI 표시 없음)
        if credit:                                     # 남의 영상 출처 표기는 규칙이라 남긴다
            ImageDraw.Draw(img).text((W // 2, 1590), credit, font=font(34, 700), fill=(235, 235, 235), anchor="mt",
                                     stroke_width=3, stroke_fill=(0, 0, 0))
        return img
    sd = ImageDraw.Draw(img)
    for y in range(0, 600):                            # 위 띠: 위로 갈수록 진하게 (큰 문구가 읽히게)
        sd.line([(0, y), (W, y)], fill=(0, 0, 0, int(40 + 190 * (1 - y / 600))))
    for y in range(1320, H):                           # 아래 띠: 자막·출처 자리
        sd.line([(0, y), (W, y)], fill=(0, 0, 0, int(60 + 170 * (y - 1320) / (H - 1320))))
    d = ImageDraw.Draw(img)
    fb = font(34, 800)
    tw = d.textlength(brand, font=fb)
    d.rounded_rectangle((70, 210, 70 + tw + 48, 270), radius=30, fill=accent)
    d.text((70 + 24, 240), brand, font=fb, fill=_on(accent), anchor="lm")
    for k in range(total):
        x = 1010 - (total - 1 - k) * 26
        d.rounded_rectangle((x - (14 if k == idx else 5), 236, x + 5, 245), radius=5, fill=accent if k == idx else (120, 120, 120))
    hook = part["kind"] == "hook"
    fnt = font(100 if hook else 88, 900)
    y = 320
    for ln in wrap(d, part.get("big") or "", fnt, 940)[:2]:
        d.text((70, y), ln, font=fnt, fill=(255, 255, 255), anchor="lt", stroke_width=6, stroke_fill=(0, 0, 0))
        y += 118 if hook else 106
    if credit:
        d.text((W // 2, 1590), credit, font=font(34, 700), fill=(225, 225, 225), anchor="mt", stroke_width=3, stroke_fill=(0, 0, 0))
    return img


def _is_key(word: str, keywords: list[str]) -> bool:
    """자막 단어가 강조어(여러 단어일 수 있음)의 일부인가. 조사가 붙어도('윈도우 앱을') 앞부분이 맞으면 강조."""
    w = re.sub(r"[.,!?…'\"]", "", word.strip())
    if len(w) < 2:
        return False
    for k in keywords:
        for tok in str(k).split():
            if (w.startswith(tok) and (len(tok) >= 2 or len(w) - len(tok) <= 2)) or (tok.startswith(w) and len(tok) - len(w) <= 1):
                return True
    return False


CAPTION_SIZE = 86                                      # 2026-09-15 사용자 지시 "자막 폰트 좀 더 크게" (66 → 86)
CAPTION_MAX_W = 900                                    # 오른쪽 좋아요·댓글 단추를 피하는 폭
CAPTION_BOTTOM = 1500                                  # 자막 아래 끝(이보다 아래는 인스타 글·계정 이름이 덮는다)


def caption_layout(draw, text: str, size: int = CAPTION_SIZE) -> tuple:
    """자막 글꼴·크기·줄. 두 줄에 안 들어가면 글자를 조금씩 줄여 잘리는 말이 없게 한다."""
    while True:
        fnt = font(size, 800)
        lines = wrap(draw, text, fnt, CAPTION_MAX_W)
        if len(lines) <= 2 or size <= 56:
            return fnt, size, lines
        size -= 4


def caption(base, text: str, keywords: list[str], theme: dict):
    """장면 위에 자막(흰 글자 + 검은 테두리, 강조어는 색)을 얹은 새 이미지."""
    from PIL import ImageDraw

    img = base.copy()
    d = ImageDraw.Draw(img)
    fnt, size, lines = caption_layout(d, text)
    accent = _hex(theme.get("caption_accent", "#ffd84d"), (255, 216, 77))
    lh = int(size * 1.33)
    y = CAPTION_BOTTOM - size - (len(lines) - 1) * lh
    for ln in lines:
        x = (W - d.textlength(ln, font=fnt)) / 2
        for w in re.split(r"(\s+)", ln):
            if not w:
                continue
            col = accent if _is_key(w, keywords) else (255, 255, 255)
            d.text((x, y), w, font=fnt, fill=col, stroke_width=max(8, size // 9), stroke_fill=(0, 0, 0))
            x += d.textlength(w, font=fnt)
        y += lh
    return img


# ───────────────────────── 4) 배경음악 (코드로 합성, 저작권 없음) ─────────────────────────

def make_bgm(seconds: float, out: Path, *, bpm: int = 84, gain: float = 0.32) -> Path:
    """잔잔한 로파이 루프: Cmaj7 → Am7 → Fmaj7 → G6, 전자피아노 느낌 화음 + 베이스 + 부드러운 킥·하이햇."""
    import numpy as np

    sr = 44100
    n = int(seconds * sr)
    t = np.arange(n) / sr
    beat = 60 / bpm
    bar = beat * 4
    chords = [[261.63, 329.63, 392.00, 493.88], [220.00, 261.63, 329.63, 392.00], [174.61, 220.00, 261.63, 329.63], [196.00, 246.94, 293.66, 329.63]]
    bass = [65.41, 55.00, 43.65, 49.00]
    out_l = np.zeros(n)
    rng = np.random.default_rng(7)

    def env(start, length, decay):
        e = np.zeros(n)
        i0, i1 = int(start * sr), min(n, int((start + length) * sr))
        if i0 >= n:
            return e
        tt = np.arange(i1 - i0) / sr
        e[i0:i1] = np.exp(-tt / decay) * np.minimum(1, tt / 0.01)
        return e

    k = 0
    while k * bar < seconds:
        ch = chords[(k // 2) % 4]
        for b in (0, 2):                                   # 화음: 1·3박에 부드럽게
            st = k * bar + b * beat
            for j, f in enumerate(ch):
                e = env(st + j * 0.012, beat * 2.2, 0.9)
                out_l += e * (np.sin(2 * math.pi * f * t) + 0.25 * np.sin(4 * math.pi * f * t)) * 0.07
        e = env(k * bar, bar, 1.2)                          # 베이스
        out_l += e * np.sin(2 * math.pi * bass[(k // 2) % 4] * t) * 0.22
        for b in range(4):
            st = k * bar + b * beat
            if b in (0, 2):                                 # 킥: 짧은 사인 스윕
                i0 = int(st * sr)
                L = min(n - i0, int(0.22 * sr))
                if L > 0:
                    tt = np.arange(L) / sr
                    out_l[i0:i0 + L] += np.sin(2 * math.pi * (55 + 60 * np.exp(-tt * 25)) * tt) * np.exp(-tt * 14) * 0.35
            i0 = int((st + beat / 2) * sr)                 # 하이햇: 엇박에 아주 작게
            L = min(n - i0, int(0.04 * sr))
            if L > 0:
                noise = np.diff(rng.standard_normal(L + 1))
                out_l[i0:i0 + L] += noise * np.exp(-np.arange(L) / sr * 90) * 0.03
        k += 1
    # 부드럽게: 한 극 저역 통과 + 앞뒤 페이드
    y = np.zeros(n)
    a = 0.18
    acc = 0.0
    for i in range(n):
        acc += a * (out_l[i] - acc)
        y[i] = acc
    fade = int(1.5 * sr)
    y[:fade] *= np.linspace(0, 1, fade)
    y[-fade:] *= np.linspace(1, 0, fade)
    y = y / (np.max(np.abs(y)) + 1e-9) * gain
    pcm = (y * 32767).astype(np.int16)
    stereo = np.column_stack([pcm, pcm]).ravel()
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(stereo.tobytes())
    return out


# ───────────────────────── 5) 조립 ─────────────────────────

def build(script: dict, out: Path, *, theme: dict, visuals: dict[int, str] | None = None, brand: str = "AI TIPS",
          engine: str | None = "edge", voice: str = "ko-KR-SunHiNeural", rate: str = "+20%", bgm: bool = True,
          bgm_gain: float = 0.32, supertonic=None, tts_opts: dict | None = None, video: dict | None = None, progress=print) -> dict:
    """대본 → mp4. engine=None 이면 목소리 없이 음악 + 자막. visuals = {카드 번호: 사진 경로}."""
    work = out.parent / (out.stem + "_work")
    work.mkdir(parents=True, exist_ok=True)
    parts = parts_of(script)
    if engine:
        engine = speak(parts, work, engine=engine, voice=voice, rate=rate, supertonic=supertonic, tts_opts=tts_opts, progress=progress)
    else:
        silent_timing(parts)
    visuals = visuals or {}
    frames: list[tuple[Path, float]] = []
    t0 = 0.0
    for i, p in enumerate(parts):
        base = overlay_scene(p, theme, brand=brand, idx=i, total=len(parts), credit=str(video.get("credit") or ""), clean=bool(video.get("clean", True))) if video else scene(p, theme, visual=visuals.get(int(p.get("card") or 0), "") if p["kind"] == "seg" else
                     (visuals.get(-1, "") if p["kind"] in ("hook", "cta") else ""), brand=brand, idx=i, total=len(parts))
        seg_len = p["dur"] + GAP
        chunks = chunk_words(p["words"]) if engine else [(0.0, p["dur"], p["say"])]
        if not chunks:
            chunks = [(0.0, p["dur"], p["say"])]
        for j, (s, _e, txt) in enumerate(chunks):
            start = 0.0 if j == 0 else s
            end = chunks[j + 1][0] if j + 1 < len(chunks) else seg_len
            f = work / f"f{i:02d}_{j:02d}.png"
            caption(base, txt, p.get("keywords") or [], theme).save(f)
            frames.append((f, max(0.2, end - start)))
        p["start"] = t0
        t0 += seg_len
    total = sum(d for _, d in frames)
    lst = work / "frames.txt"
    lines = []
    for f, d in frames:
        lines += [f"file '{f.as_posix()}'", f"duration {d:.3f}"]
    lines.append(f"file '{frames[-1][0].as_posix()}'")
    lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
    off = 2 if video else 1                            # 영상 해설형이면 0번 입력 = 원본 영상(반복), 1번 = 글자 층
    inputs = (["-stream_loop", "-1", "-i", str(video["path"])] if video else []) + ["-f", "concat", "-safe", "0", "-i", str(lst)]
    filt: list[str] = []
    amap = None
    if engine:
        # 목소리 이어 붙이기(구간 사이 GAP)
        for p in parts:
            inputs += ["-i", p["audio"]]
        vparts = "".join(f"[{off + i}:a]aresample=48000,apad=pad_dur={GAP}[s{i}];" for i in range(len(parts)))
        filt.append(vparts + "".join(f"[s{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[voice]")
        amap = "[voice]"
    if bgm:
        wav = make_bgm(total + 1, work / "bgm.wav", gain=bgm_gain)
        inputs += ["-i", str(wav)]
        bi = off + (len(parts) if engine else 0)
        if engine:
            filt.append(f"[voice]asplit[v1][v2];[{bi}:a]aresample=48000,volume=0.55[b];[b][v2]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=350[bd];"
                        f"[v1][bd]amix=inputs=2:duration=first:normalize=0[mix]")
            amap = "[mix]"
        else:
            filt.append(f"[{bi}:a]aresample=48000[mix]")
            amap = "[mix]"
    if amap:                                          # 목소리마다 음량이 달라서(평균 -19~-24dB) 인스타 권장 수준(-14 LUFS)으로 맞춘다
        filt.append(f"{amap}loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[out]")
        amap = "[out]"
    vmap, vf = "0:v", ["-vf", f"fps={FPS},format=yuv420p"]
    if video:                                          # 원본 영상 바탕 + 글자 층 (세로 원본은 화면 전체, 가로·정사각은 흐린 전체 + 가운데 상자)
        filt.append(video_chain(*_dims(video["path"])) + f"[1:v]format=rgba[ov];[base][ov]overlay=0:0,fps={FPS},format=yuv420p[v]")
        vmap, vf = "[v]", []
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs]
    if filt:
        cmd += ["-filter_complex", ";".join(filt)]
    cmd += ["-map", vmap] + (["-map", amap] if amap else []) + [
        *vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", f"{total:.2f}", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    progress(f"릴스 v2 {total:.0f}초 · 구간 {len(parts)} · 자막 {len(frames)}장 · 목소리 {engine or '없음'} · 음악 {'있음' if bgm else '없음'}")
    (work / "script.json").write_text(json.dumps({"parts": [{k: v for k, v in p.items() if k != 'words'} for p in parts]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"path": str(out), "duration": duration_of(out), "parts": parts}
