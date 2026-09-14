"""카드 → 나레이션 릴스. 렌더한 카드(1080×1350)를 세로 영상(1080×1920)으로 이어 붙이고, 카드 글을 TTS 로 읽어 나레이션을 얹는다.

왜: 카드뉴스는 팔로워에게만 배포되고 릴스는 비팔로워에게도 배포된다(사용자 결정 2026-09-14 — 팔로워 0 계정은 릴스가 유일한 통로).
무음 릴스는 넘겨지므로(사용자 지적) 카드 글을 그대로 읽는 나레이션을 붙인다 — 한국 정보 계정들의 표준 방식(TTS + 자막 + 카드 넘김).

TTS: edge-tts(마이크로소프트 엣지 음성, 무료·키 없음). 실패하면 RuntimeError — 호출한 쪽이 카드뉴스로 되돌린다.
영상: 카드마다 흐린 확대 배경 + 카드 본체(느린 확대), 길이는 그 카드의 나레이션 길이 + 0.6초. 첫 카드는 최소 3초.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
from pathlib import Path

DEFAULT_VOICE = "ko-KR-SunHiNeural"     # 여성. 남성은 ko-KR-InJoonNeural
DEFAULT_RATE = "+12%"
GAP_SEC = 0.6
MIN_FIRST_SEC = 3.0
MAX_TOTAL_SEC = 75.0        # 릴스는 30~60초가 가장 잘 돈다 — 카드 글을 다 읽되 길면 뒤 카드를 뺀다


def narration_for(slide: dict, cta_prefix: str = "") -> str:
    """카드 한 장의 나레이션 문장. 표지 = 제목+부제, 본문 = 소제목+문장들, 마무리 = 저장·공유 유도."""
    kind = slide.get("kind")
    if kind == "cover":
        parts = [slide.get("title", ""), slide.get("sub", "")]
    elif kind == "cta":
        parts = [cta_prefix or "", slide.get("cta", "") or "저장해 두고 하나씩 써 보세요."]
    else:
        parts = [slide.get("title", "")] + list(slide.get("lines") or [])
        if slide.get("prompt"):
            parts.append("입력 예시는 화면을 확인해 주세요.")
    text = " ".join(str(p).strip() for p in parts if str(p).strip())
    text = re.sub(r"[\U0001F300-\U0001FAFF☀-➿⭐✅️#*_`]", " ", text)   # 이모지·기호는 읽지 않는다
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 190:                       # 카드 한 장에 7~8초 넘게 읽지 않는다 — 문장 단위로 자른다
        cut = text[:190]
        text = cut[:cut.rfind(".") + 1] if cut.rfind(".") > 80 else cut
    return text


def duration_of(path: Path | str) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip() or 0)


async def _tts_all(texts: list[str], paths: list[Path], voice: str, rate: str) -> None:
    import edge_tts  # type: ignore

    for t, p in zip(texts, paths):
        await edge_tts.Communicate(t or "다음.", voice, rate=rate).save(str(p))


def synthesize(texts: list[str], out_dir: Path, *, voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE) -> list[Path]:
    """문장마다 mp3 하나. 실패하면 RuntimeError."""
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = [out_dir / f"nar{i:02d}.mp3" for i in range(len(texts))]
    try:
        asyncio.run(_tts_all(texts, paths, voice, rate))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"TTS 실패: {type(exc).__name__}: {str(exc)[:120]}") from exc
    for p in paths:
        if not p.exists() or p.stat().st_size < 1000:
            raise RuntimeError(f"TTS 결과가 비어 있음: {p.name}")
    return paths


def ffmpeg_command(cards: list[Path], audios: list[Path], durs: list[float], out: Path, *, bg: str = "#15171c") -> list[str]:
    """카드 n장 + 나레이션 n개 → 1080×1920 mp4 명령. (순수 함수: 테스트용)"""
    n = len(cards)
    inputs: list[str] = []
    filters: list[str] = []
    for i, (c, du) in enumerate(zip(cards, durs)):
        inputs += ["-loop", "1", "-framerate", "30", "-t", f"{du:.2f}", "-i", str(c)]
        filters.append(
            f"[{i}:v]split[a{i}][b{i}];"
            f"[a{i}]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=30,eq=brightness=-0.15[bg{i}];"
            f"[b{i}]zoompan=z='min(zoom+0.0006,1.05)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1350:fps=30[fg{i}];"
            f"[bg{i}][fg{i}]overlay=0:285,setsar=1,format=yuv420p[v{i}]")
    for a in audios:
        inputs += ["-i", str(a)]
    vcat = "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    acat = "".join(f"[{n + i}:a]apad=pad_dur={GAP_SEC}[a{i}p];" for i in range(n)) + "".join(f"[a{i}p]" for i in range(n)) + f"concat=n={n}:v=0:a=1[a]"
    return ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters) + ";" + vcat + ";" + acat,
            "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-crf", "23", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-t", str(MAX_TOTAL_SEC), "-movflags", "+faststart", str(out)]


def build(cards: list[Path | str], slides: list[dict], out: Path, *, voice: str = DEFAULT_VOICE, rate: str = DEFAULT_RATE,
          cta_prefix: str = "", progress=print, synth=synthesize) -> dict:
    """카드 파일들 + 슬라이드 정보 → 나레이션 릴스. 반환 {path, duration, narration: [..]}."""
    cards = [Path(c) for c in cards]
    if len(cards) != len(slides):
        slides = (slides + [{}] * len(cards))[:len(cards)]
    texts = [narration_for(s, cta_prefix) for s in slides]
    work = out.parent / "narration"
    audios = synth(texts, work, voice=voice, rate=rate)
    durs = [duration_of(a) + GAP_SEC for a in audios]
    durs[0] = max(durs[0], MIN_FIRST_SEC)
    total = sum(durs)
    if total > MAX_TOTAL_SEC:                       # 너무 길면 뒤 카드부터 뺀다(마무리 카드는 남긴다)
        while total > MAX_TOTAL_SEC and len(cards) > 3:
            cards.pop(-2); audios.pop(-2); durs.pop(-2); texts.pop(-2)
            total = sum(durs)
    subprocess.run(ffmpeg_command(cards, audios, durs, out), check=True, capture_output=True, text=True)
    progress(f"나레이션 릴스 {total:.0f}초 · 카드 {len(cards)}장 · 음성 {voice}")
    return {"path": str(out), "duration": duration_of(out), "narration": texts}
