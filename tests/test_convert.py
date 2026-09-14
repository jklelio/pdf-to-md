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


def test_garbage_ratio_is_zero_for_clean_text():
    assert convert._garbage_ratio("Este e um contrato de prestacao de servicos.") == 0.0


def test_garbage_ratio_is_high_for_mostly_replacement_chars():
    text = "�" * 90 + "ok" * 5
    assert convert._garbage_ratio(text) > 0.5


def test_extract_text_pdf_rejects_high_volume_but_garbled_text(tmp_path, monkeypatch):
    pdf_path = tmp_path / "folha_de_ponto.pdf"
    garbled_page = "�" * 60 + " Rerva LxaliBelS ArdavAo Eemen "
    monkeypatch.setattr(convert, "_is_scanned_document", lambda p: False)
    monkeypatch.setattr(convert, "_pages_text", lambda p: [garbled_page, garbled_page])

    result = convert.extract_text_pdf(pdf_path)

    assert result is None


def _make_scanned_pdf_with_overlay_text(path: Path, overlay_text: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100), False)
    pixmap.set_rect(pixmap.irect, (255, 255, 255))
    page.insert_image(page.rect, pixmap=pixmap)
    page.insert_text((72, 72), overlay_text, fontsize=12)
    doc.save(path)
    doc.close()


def test_extract_text_pdf_rejects_full_page_scanned_image_even_with_lots_of_overlay_text(
    tmp_path,
):
    pdf_path = tmp_path / "scan_com_texto_embutido.pdf"
    plenty_of_valid_looking_text = "Eru Map WMotgilhagol Ibi Ardav Eemen da Red " * 20
    _make_scanned_pdf_with_overlay_text(pdf_path, plenty_of_valid_looking_text)

    result = convert.extract_text_pdf(pdf_path)

    assert result is None


import pytesseract


def _make_one_page_pdf(path: Path) -> None:
    doc = fitz.open()
    doc.new_page()
    doc.save(path)
    doc.close()


def test_ocr_pdf_returns_high_confidence_text(tmp_path, monkeypatch):
    pdf_path = tmp_path / "scan.pdf"
    _make_one_page_pdf(pdf_path)

    def fake_image_to_data(image, output_type):
        return {
            "text": ["Ola", "mundo", ""],
            "conf": ["95", "90", "-1"],
        }

    monkeypatch.setattr(pytesseract, "image_to_data", fake_image_to_data)

    text, confidence = convert.ocr_pdf(pdf_path)
    assert "Ola" in text
    assert "mundo" in text
    assert confidence == 92.5


def test_ocr_pdf_returns_low_confidence_for_garbled_scan(tmp_path, monkeypatch):
    pdf_path = tmp_path / "scan_ruim.pdf"
    _make_one_page_pdf(pdf_path)

    def fake_image_to_data(image, output_type):
        return {
            "text": ["x1z", "##q"],
            "conf": ["12", "8"],
        }

    monkeypatch.setattr(pytesseract, "image_to_data", fake_image_to_data)

    _, confidence = convert.ocr_pdf(pdf_path)
    assert confidence == 10.0


def test_convert_redirects_for_text_pdf(tmp_path):
    pdf_path = tmp_path / "contrato.pdf"
    long_paragraph = "Este e um contrato de prestacao de servicos. " * 10
    _make_text_pdf(pdf_path, [long_paragraph])

    result = convert.convert(pdf_path)

    assert result.outcome == "redirect"
    assert result.md_path == tmp_path / ".pdf-cache" / "contrato.md"
    assert result.md_path.exists()
    assert "contrato" in result.md_path.read_text(encoding="utf-8").lower()


def test_convert_reuses_valid_cache_without_reconverting(tmp_path, monkeypatch):
    pdf_path = tmp_path / "contrato.pdf"
    long_paragraph = "Este e um contrato de prestacao de servicos. " * 10
    _make_text_pdf(pdf_path, [long_paragraph])

    first = convert.convert(pdf_path)
    assert first.outcome == "redirect"

    def fail_if_called(pdf_path):
        raise AssertionError("extract_text_pdf should not be called on a cache hit")

    monkeypatch.setattr(convert, "extract_text_pdf", fail_if_called)

    second = convert.convert(pdf_path)
    assert second.outcome == "redirect"
    assert second.message == "cached conversion reused"


def test_convert_allows_through_when_ocr_confidence_low(tmp_path, monkeypatch):
    pdf_path = tmp_path / "scan_ruim.pdf"
    _make_blank_pdf(pdf_path, page_count=1)

    monkeypatch.setattr(convert, "ocr_pdf", lambda p: ("lixo", 10.0))

    result = convert.convert(pdf_path)

    assert result.outcome == "allow"
    assert result.md_path is None


def test_record_failure_increments_and_persists(tmp_path):
    meta_path = tmp_path / ".pdf-cache" / "doc.meta.json"
    assert convert.record_failure(meta_path) == 1
    assert convert.record_failure(meta_path) == 2
    assert convert.load_meta(meta_path)["fail_count"] == 2


def test_reset_failure_zeroes_existing_count(tmp_path):
    meta_path = tmp_path / ".pdf-cache" / "doc.meta.json"
    convert.record_failure(meta_path)
    convert.reset_failure(meta_path)
    assert convert.load_meta(meta_path)["fail_count"] == 0
