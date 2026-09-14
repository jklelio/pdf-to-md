from __future__ import annotations

import json
from pathlib import Path

import io
from dataclasses import dataclass

import pymupdf as fitz
import pytesseract
from PIL import Image

TEXT_CHARS_PER_PAGE_THRESHOLD = 40
OCR_CONFIDENCE_THRESHOLD = 70.0
GARBAGE_CHAR_RATIO_THRESHOLD = 0.02
IMAGE_DOMINANCE_AREA_RATIO = 0.9
SCANNED_PAGE_FRACTION_THRESHOLD = 0.5


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


def _pages_text(pdf_path: Path) -> list[str]:
    doc = fitz.open(pdf_path)
    try:
        return [page.get_text() for page in doc]
    finally:
        doc.close()


def _garbage_ratio(text: str) -> float:
    if not text:
        return 0.0
    garbage_chars = sum(
        1 for ch in text if ch == "�" or (ord(ch) < 32 and ch not in "\n\r\t")
    )
    return garbage_chars / len(text)


def _page_is_image_dominant(page) -> bool:
    page_area = page.rect.width * page.rect.height
    if page_area <= 0:
        return False
    for img in page.get_images(full=True):
        xref = img[0]
        for bbox in page.get_image_rects(xref):
            if (bbox.width * bbox.height) / page_area >= IMAGE_DOMINANCE_AREA_RATIO:
                return True
    return False


def _is_scanned_document(pdf_path: Path) -> bool:
    doc = fitz.open(pdf_path)
    try:
        page_count = len(doc)
        if page_count == 0:
            return False
        scanned_pages = sum(1 for page in doc if _page_is_image_dominant(page))
        return (scanned_pages / page_count) >= SCANNED_PAGE_FRACTION_THRESHOLD
    finally:
        doc.close()


def extract_text_pdf(pdf_path: Path) -> str | None:
    if _is_scanned_document(pdf_path):
        return None

    pages_text = _pages_text(pdf_path)

    if not pages_text:
        return None

    avg_chars_per_page = sum(len(t) for t in pages_text) / len(pages_text)
    if avg_chars_per_page <= TEXT_CHARS_PER_PAGE_THRESHOLD:
        return None

    combined_text = "\n\n".join(pages_text)
    if _garbage_ratio(combined_text) > GARBAGE_CHAR_RATIO_THRESHOLD:
        return None

    return combined_text


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


@dataclass
class ConversionResult:
    outcome: str  # "redirect" or "allow"
    md_path: Path | None
    message: str


def convert(pdf_path: Path) -> ConversionResult:
    md_path, meta_path = cache_paths(pdf_path)
    meta = load_meta(meta_path)

    if md_path.exists() and is_cache_valid(pdf_path, meta):
        return ConversionResult("redirect", md_path, "cached conversion reused")

    text = extract_text_pdf(pdf_path)
    if text is not None:
        _write_conversion(pdf_path, md_path, meta_path, text)
        return ConversionResult("redirect", md_path, "converted from embedded text")

    ocr_text, confidence = ocr_pdf(pdf_path)
    if confidence >= OCR_CONFIDENCE_THRESHOLD:
        _write_conversion(pdf_path, md_path, meta_path, ocr_text)
        return ConversionResult(
            "redirect", md_path, f"converted via OCR (confidence {confidence:.0f})"
        )

    reset_failure(meta_path)
    return ConversionResult(
        "allow",
        None,
        f"OCR confidence too low ({confidence:.0f} < {OCR_CONFIDENCE_THRESHOLD:.0f}); "
        "reading original PDF",
    )


def _write_conversion(pdf_path: Path, md_path: Path, meta_path: Path, text: str) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(text, encoding="utf-8")
    stat = pdf_path.stat()
    save_meta(meta_path, {"size": stat.st_size, "mtime": stat.st_mtime, "fail_count": 0})


def record_failure(meta_path: Path) -> int:
    meta = load_meta(meta_path)
    count = meta.get("fail_count", 0) + 1
    meta["fail_count"] = count
    save_meta(meta_path, meta)
    return count


def reset_failure(meta_path: Path) -> None:
    meta = load_meta(meta_path)
    if meta.get("fail_count"):
        meta["fail_count"] = 0
        save_meta(meta_path, meta)
