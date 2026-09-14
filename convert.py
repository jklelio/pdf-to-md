from __future__ import annotations

import json
from pathlib import Path


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
