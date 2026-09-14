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


import fitz


def _make_text_pdf(path: Path, paragraphs: list[str]) -> None:
    doc = fitz.open()
    for paragraph in paragraphs:
        page = doc.new_page()
        page.insert_text((72, 72), paragraph, fontsize=12)
    doc.save(path)
    doc.close()


def _make_blank_pdf(path: Path, page_count: int) -> None:
    doc = fitz.open()
    for _ in range(page_count):
        doc.new_page()
    doc.save(path)
    doc.close()


def test_extract_text_pdf_returns_text_for_real_text_pdf(tmp_path):
    pdf_path = tmp_path / "contrato.pdf"
    long_paragraph = "Este e um contrato de prestacao de servicos. " * 10
    _make_text_pdf(pdf_path, [long_paragraph, long_paragraph])
    result = convert.extract_text_pdf(pdf_path)
    assert result is not None
    assert "contrato" in result.lower()


def test_extract_text_pdf_returns_none_for_blank_pdf(tmp_path):
    pdf_path = tmp_path / "escaneado.pdf"
    _make_blank_pdf(pdf_path, page_count=2)
    result = convert.extract_text_pdf(pdf_path)
    assert result is None
