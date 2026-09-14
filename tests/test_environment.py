import shutil

import fitz  # noqa: F401  (pymupdf)
import pytesseract
from PIL import Image  # noqa: F401


def test_pymupdf_importable():
    assert fitz.__doc__ is not None


def test_tesseract_binary_on_path():
    assert shutil.which("tesseract") is not None, (
        "tesseract executable not found on PATH — install it from "
        "https://github.com/UB-Mannheim/tesseract/wiki and add it to PATH"
    )


def test_pytesseract_can_reach_tesseract():
    version = pytesseract.get_tesseract_version()
    assert version is not None
