"""질의순서 HWP → 이미지. 원본 양식 그대로 보여 주려고 만든다.

LibreOffice(+H2Orestart 한글 필터)로 PDF 를 만들고, 그 PDF 를 PNG 로 뽑는다.
이준석 위원이 있는 행은 배경을 칠한다 — PDF 가 아니라 **이미지에서** 칠한다.
PDF 에 칠하면 셀의 흰 배경이 위를 덮어 '비고' 칸이 안 칠해진다(2026-11-06 확인).

워크플로가 LibreOffice 를 깔아 둔 실행에서만 쓴다(질의순서 첨부가 있을 때만).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

DPI = 150
LIGHT = 190          # 이보다 밝으면 빈 바탕으로 보고 색을 칠한다(글자·테두리는 어둡다)


def is_order_file(name: str, keyword: str = "질의순서") -> bool:
    """질의순서 한글 파일인가."""
    return keyword in name and name.lower().endswith((".hwp", ".hwpx"))


def hex_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


def to_pdf(hwp: Path, out_dir: Path, timeout: int = 180) -> Path:
    """LibreOffice 로 PDF 변환. 실패하면 RuntimeError."""
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", str(hwp), "--outdir", str(out_dir)],
                   check=True, capture_output=True, timeout=timeout)
    pdf = out_dir / (hwp.stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError(f"한글 변환 실패: {hwp.name}")
    return pdf


def row_boxes(page, name: str) -> list:
    """name 이 있는 표 행의 사각형(표 좌우 끝까지). 표를 못 찾으면 빈 목록."""
    import fitz

    wide = [d["rect"] for d in page.get_drawings() if d["rect"].width > page.rect.width * 0.5]
    if not wide:
        return []
    x0, x1 = min(r.x0 for r in wide), max(r.x1 for r in wide)
    lines = sorted({round(r.y0, 1) for r in wide if r.height < 2})
    out = []
    for hit in page.search_for(name):
        mid = (hit.y0 + hit.y1) / 2
        top = max((y for y in lines if y <= mid), default=hit.y0 - 2)
        bottom = min((y for y in lines if y >= mid), default=hit.y1 + 2)
        out.append(fitz.Rect(x0, top, x1, bottom))
    return out


def _paint(img, box, rgb: tuple[int, int, int], scale: float) -> None:
    area = (int(box.x0 * scale), int(box.y0 * scale), int(box.x1 * scale), int(box.y1 * scale))
    crop = img.crop(area)
    px = crop.load()
    for y in range(crop.height):
        for x in range(crop.width):
            r, g, b = px[x, y][:3]
            if r > LIGHT and g > LIGHT and b > LIGHT:
                px[x, y] = rgb
    img.paste(crop, area)


def to_images(pdf: Path, out_dir: Path, highlight: str = "", color: str = "#FF7210") -> list[Path]:
    """PDF → 쪽마다 PNG. highlight 이름이 있는 행은 color 로 채운다."""
    import fitz
    from PIL import Image

    rgb = hex_rgb(color)
    scale = DPI / 72
    doc = fitz.open(pdf)
    out = []
    for i in range(len(doc)):
        page = doc[i]
        boxes = row_boxes(page, highlight) if highlight else []
        pix = page.get_pixmap(dpi=DPI)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        for box in boxes:
            _paint(img, box, rgb, scale)
        path = out_dir / f"{pdf.stem}-{i + 1}.png"
        img.save(path)
        out.append(path)
    return out


def has_name(pdf: Path, name: str) -> bool:
    """문서 어디에든 이 이름이 있나."""
    import fitz

    doc = fitz.open(pdf)
    return any(doc[i].search_for(name) for i in range(len(doc)))


def convert(hwp: Path, out_dir: Path, highlight: str = "", color: str = "#FF7210") -> list[Path]:
    """한글 파일 하나 → PNG 목록.

    highlight 이름이 문서에 없으면 빈 목록 — 이준석 위원이 질의하지 않는 날의
    질의순서는 보내지 않는다(사용자 결정 2026-11-09).
    """
    pdf = to_pdf(hwp, out_dir)
    if highlight and not has_name(pdf, highlight):
        return []
    return to_images(pdf, out_dir, highlight, color)
