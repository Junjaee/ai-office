"""말하는 대본 → 자막 싱크 릴스 (릴스 v2, 2026-09-14).

v1(insta_slideshow)은 카드 글을 그대로 읽어 부자연스러웠다(사용자 지적 → 중지). v2 는 한국 정보 릴스의 실제 방식을 따른다
(research/릴스_나레이션_리서치_2026-09-14.md):
1) 편집장이 카드와 별도로 **말하는 대본**을 쓴다 — 훅(3초 안) → 핵심 2~4 → 행동. 20~35초. (script_prompt, REEL_SCRIPT_SCHEMA)
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
        "segments": {"type": "array", "minItems": 2, "maxItems": 4,
                     "items": {"type": "object", "required": ["say", "big"],
                               "properties": {"say": {"type": "string", "maxLength": 130}, "big": {"type": "string", "maxLength": 22},
                                              "card": {"type": "integer"}, "keywords": {"type": "array", "items": {"type": "string"}}}}},
        "cta": {"type": "object", "required": ["say", "big"],
                "properties": {"say": {"type": "string", "maxLength": 80}, "big": {"type": "string", "maxLength": 22}}},
    },
}


# ───────────────────────── 1) 말하는 대본 ─────────────────────────

def script_prompt(profile_name: str, audience: str, article: dict, slides: list[dict], dm_keyword: str = "") -> tuple[str, str]:
    system = (f"당신은 인스타그램 정보 계정 '{profile_name}'의 릴스 대본 작가입니다. 독자: {audience}\n"
              "카드뉴스로 쓴 기사를 **귀로 듣는 20~35초 릴스 나레이션**으로 다시 씁니다. 카드 문장을 그대로 옮기지 않습니다.\n"
              "말투 규칙:\n"
              "- 친구에게 말하듯 자연스러운 구어체 존댓말(~해요/~거든요/~더라고요). 한 문장 25자 안팎, 쉼표로 호흡을 끊는다.\n"
              "- 괄호·영문 병기·가운뎃점·슬래시·이모지 금지(예: '제미나이(Gemini)' → '제미나이'). 단축키는 'Alt 키랑 스페이스바'처럼 말로.\n"
              "- 숫자는 소리 내 읽기 쉽게('1,000원' → '천 원', '47%' → '47퍼센트'). 날짜는 꼭 필요할 때만.\n"
              "- 사실은 기사 안의 것만. 과장·감탄사 남발 금지.\n"
              "구성:\n"
              "- hook: 첫 3초 안에 끝나는 한 문장(15~28자). 시청자에게 직접 말 걸기, 결과 먼저, 숫자·손해 자극 중 하나. 제목을 그대로 읽지 않는다.\n"
              "- segments 2~4개: 각 1~2문장. 핵심만(무엇이 되는지 → 어떻게 하는지 → 조건). big 은 그 구간 화면에 크게 뜰 8~14자 요약, "
              "keywords 는 자막에서 색으로 강조할 단어 1~2개, card 는 그 구간에 보여 줄 카드 번호(아래 목록에서 사진 있는 카드), 없으면 0.\n"
              "- cta: 한 문장. " + (f"댓글 키워드는 반드시 '{dm_keyword}' 그대로 쓴다(바꾸지 않는다): \"댓글에 '{dm_keyword}' 남기면 ~을 DM으로 보내드려요\" 꼴"
                                    if dm_keyword else "저장·공유 유도") + ".\n"
              "- 전체 말 분량(hook+segments+cta 의 say 합) 180~260자(25~35초). segments 는 3개가 기본.\n"
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
        cta["say"] = f"댓글에 '{kw}' 남겨 주시면, 정리한 내용을 DM으로 보내드려요."
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


def speak(parts: list[dict], work: Path, *, engine: str = "edge", voice: str = "ko-KR-SunHiNeural", rate: str = "+20%",
          supertonic=None) -> None:
    """구간마다 음성 파일(p['audio'])과 길이(p['dur'])와 단어 시각(p['words'])을 채운다."""
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


def chunk_words(words: list[tuple[float, float, str]], max_chars: int = 13) -> list[tuple[float, float, str]]:
    """단어들을 자막 한 줄(13자 안팎) 단위로 묶는다."""
    out, cur, start, end = [], [], 0.0, 0.0
    for s, e, w in words:
        if cur and len(" ".join(cur + [w])) > max_chars:
            out.append((start, end, " ".join(cur)))
            cur = []
        if not cur:
            start = s
        cur.append(w)
        end = e
    if cur:
        out.append((start, end, " ".join(cur)))
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


def caption(base, text: str, keywords: list[str], theme: dict):
    """장면 위에 자막(흰 글자 + 검은 테두리, 강조어는 색)을 얹은 새 이미지."""
    from PIL import ImageDraw

    img = base.copy()
    d = ImageDraw.Draw(img)
    fnt = font(66, 800)
    accent = _hex(theme.get("caption_accent", "#ffd84d"), (255, 216, 77))
    lines = wrap(d, text, fnt, 900)[:2]
    y = 1395 - (len(lines) - 1) * 44
    for ln in lines:
        x = (W - d.textlength(ln, font=fnt)) / 2
        for w in re.split(r"(\s+)", ln):
            if not w:
                continue
            col = accent if _is_key(w, keywords) else (255, 255, 255)
            d.text((x, y), w, font=fnt, fill=col, stroke_width=8, stroke_fill=(0, 0, 0))
            x += d.textlength(w, font=fnt)
        y += 88
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
          bgm_gain: float = 0.32, supertonic=None, progress=print) -> dict:
    """대본 → mp4. engine=None 이면 목소리 없이 음악 + 자막. visuals = {카드 번호: 사진 경로}."""
    work = out.parent / (out.stem + "_work")
    work.mkdir(parents=True, exist_ok=True)
    parts = parts_of(script)
    if engine:
        speak(parts, work, engine=engine, voice=voice, rate=rate, supertonic=supertonic)
    else:
        silent_timing(parts)
    visuals = visuals or {}
    frames: list[tuple[Path, float]] = []
    t0 = 0.0
    for i, p in enumerate(parts):
        base = scene(p, theme, visual=visuals.get(int(p.get("card") or 0), "") if p["kind"] == "seg" else
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
    inputs = ["-f", "concat", "-safe", "0", "-i", str(lst)]
    filt: list[str] = []
    amap = None
    if engine:
        # 목소리 이어 붙이기(구간 사이 GAP)
        for p in parts:
            inputs += ["-i", p["audio"]]
        vparts = "".join(f"[{1 + i}:a]aresample=48000,apad=pad_dur={GAP}[s{i}];" for i in range(len(parts)))
        filt.append(vparts + "".join(f"[s{i}]" for i in range(len(parts))) + f"concat=n={len(parts)}:v=0:a=1[voice]")
        amap = "[voice]"
    if bgm:
        wav = make_bgm(total + 1, work / "bgm.wav", gain=bgm_gain)
        inputs += ["-i", str(wav)]
        bi = 1 + (len(parts) if engine else 0)
        if engine:
            filt.append(f"[voice]asplit[v1][v2];[{bi}:a]aresample=48000,volume=0.55[b];[b][v2]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=350[bd];"
                        f"[v1][bd]amix=inputs=2:duration=first:normalize=0[mix]")
            amap = "[mix]"
        else:
            filt.append(f"[{bi}:a]aresample=48000[mix]")
            amap = "[mix]"
    cmd = ["ffmpeg", "-y", "-v", "error", *inputs]
    if filt:
        cmd += ["-filter_complex", ";".join(filt)]
    cmd += ["-map", "0:v"] + (["-map", amap] if amap else []) + [
        "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-t", f"{total:.2f}", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    progress(f"릴스 v2 {total:.0f}초 · 구간 {len(parts)} · 자막 {len(frames)}장 · 목소리 {engine or '없음'} · 음악 {'있음' if bgm else '없음'}")
    (work / "script.json").write_text(json.dumps({"parts": [{k: v for k, v in p.items() if k != 'words'} for p in parts]}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"path": str(out), "duration": duration_of(out), "parts": parts}
