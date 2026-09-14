from __future__ import annotations

import json
from pathlib import Path

import io

import fitz
import pytesseract
from PIL import Image

TEXT_CHARS_PER_PAGE_THRESHOLD = 40
OCR_CONFIDENCE_THRESHOLD = 70.0


def cache_paths(pdf_path: Path) -> tuple[Path, Path]:
    cache_dir = pdf_path.parent / ".pdf-cache"
    stem = pdf_path.stem
    return cache_dir / f"{stem}.md", cache_dir / f"{stem}.meta.json"


def load_meta(meta_path: Path) -> dict:
    if not meta_path.exists():
        return {}
    return json.loads(meta_path.read_text(encoding="utf-8"))


def save_meta(meta_path: Path, data: dict) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(data), encoding="utf-8")


def is_cache_valid(pdf_path: Path, meta: dict) -> bool:
    if "size" not in meta or "mtime" not in meta:
        return False
    stat = pdf_path.stat()
    return meta["size"] == stat.st_size and meta["mtime"] == stat.st_mtime


def extract_text_pdf(pdf_path: Path) -> str | None:
    doc = fitz.open(pdf_path)
    try:
        pages_text = [page.get_text() for page in doc]
    finally:
        doc.close()

    if not pages_text:
        return None

    avg_chars_per_page = sum(len(t) for t in pages_text) / len(pages_text)
    if avg_chars_per_page <= TEXT_CHARS_PER_PAGE_THRESHOLD:
        return None

    return "\n\n".join(pages_text)


def ocr_pdf(pdf_path: Path) -> tuple[str, float]:
    doc = fitz.open(pdf_path)
    try:
        page_texts: list[str] = []
        confidences: list[float] = []
        for page in doc:
            pixmap = page.get_pixmap(dpi=200)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

            words: list[str] = []
            for word, conf_str in zip(data["text"], data["conf"]):
                confidence = float(conf_str)
                if word.strip() and confidence >= 0:
                    words.append(word)
                    confidences.append(confidence)
            page_texts.append(" ".join(words))
    finally:
        doc.close()

    average_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    return "\n\n".join(page_texts), average_confidence
