import json
from pathlib import Path

import convert


def test_cache_paths_are_inside_dot_pdf_cache_next_to_source(tmp_path):
    pdf_path = tmp_path / "contrato.pdf"
    md_path, meta_path = convert.cache_paths(pdf_path)
    assert md_path == tmp_path / ".pdf-cache" / "contrato.md"
    assert meta_path == tmp_path / ".pdf-cache" / "contrato.meta.json"


def test_load_meta_returns_empty_dict_when_missing(tmp_path):
    meta_path = tmp_path / ".pdf-cache" / "missing.meta.json"
    assert convert.load_meta(meta_path) == {}


def test_save_meta_then_load_meta_round_trips(tmp_path):
    meta_path = tmp_path / ".pdf-cache" / "doc.meta.json"
    convert.save_meta(meta_path, {"size": 123, "mtime": 456.0, "fail_count": 0})
    assert convert.load_meta(meta_path) == {"size": 123, "mtime": 456.0, "fail_count": 0}
    assert json.loads(meta_path.read_text(encoding="utf-8")) == {
        "size": 123,
        "mtime": 456.0,
        "fail_count": 0,
    }


def test_is_cache_valid_true_when_size_and_mtime_match(tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    stat = pdf_path.stat()
    meta = {"size": stat.st_size, "mtime": stat.st_mtime}
    assert convert.is_cache_valid(pdf_path, meta) is True


def test_is_cache_valid_false_when_size_differs(tmp_path):
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    stat = pdf_path.stat()
    meta = {"size": stat.st_size + 1, "mtime": stat.st_mtime}
    assert convert.is_cache_valid(pdf_path, meta) is False
