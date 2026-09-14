from __future__ import annotations

import json
from pathlib import Path

import fitz

TEXT_CHARS_PER_PAGE_THRESHOLD = 40


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
