# PDF-to-Markdown Hook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code hook that automatically converts any PDF Claude tries to read into markdown (text extraction, or OCR when scanned), so PDFs cost far fewer tokens to read — with strict, visible error handling instead of silent fallback, and no separate API billing.

**Architecture:** A pure conversion library (`convert.py`) implements the decision logic (text extraction → OCR → allow-as-is) and is unit tested in isolation. A thin `hook.py` wraps it as a Claude Code `PreToolUse` hook: reads the tool-call JSON from stdin, calls `convert.py`, and writes a `deny` (redirect to the generated `.md`) or `allow` decision to stdout. The hook is registered globally in `~/.claude/settings.json` so it applies to every project.

**Tech Stack:** Python 3.13 (already installed on this machine), PyMuPDF (`fitz`) for PDF text/image extraction, `pytesseract` + Pillow for OCR, the Tesseract OCR Windows binary, `pytest` for tests.

**Spec:** [docs/superpowers/specs/2026-09-13-pdf-to-md-hook-design.md](../specs/2026-09-13-pdf-to-md-hook-design.md)

## Global Constraints

- Text-extraction threshold: average **> 40 characters/page** of directly extracted text means "real text PDF" (spec section "Decision logic", step 2).
- OCR confidence threshold: average Tesseract word confidence **>= 70** means "OCR is good enough" (spec step 3).
- Cache lives in `.pdf-cache/` next to the source PDF: `<stem>.md` plus `<stem>.meta.json` (spec "Components", #4).
- On conversion error: 1st consecutive failure for a given PDF → **block** the Read with the exact error message (do not fall back). 2nd consecutive failure on the same PDF → **allow** the original Read, with a message that says this is an unresolved-error fallback, and reset the failure count (spec "Decision logic", step 4, as amended by the user).
- No separate Anthropic API key anywhere in this project (spec "Non-goals").
- All file paths in this plan are absolute under `C:\Users\jklel\CLAUDE\pdf-to-md\`.

---

## Task 1: Prerequisites — install dependencies and verify the environment

**Files:**
- Create: `C:\Users\jklel\CLAUDE\pdf-to-md\requirements.txt`
- Create: `C:\Users\jklel\CLAUDE\pdf-to-md\tests\test_environment.py`

**Interfaces:**
- Produces: a working `python` on PATH with `fitz`, `pytesseract`, `PIL` importable, and a `tesseract` executable on PATH — everything downstream depends on this.

- [ ] **Step 1: Write requirements.txt**

```
pymupdf
pytesseract
Pillow
pytest
```

- [ ] **Step 2: Install the Python packages**

Run in Git Bash, from `C:\Users\jklel\CLAUDE\pdf-to-md`:

```bash
python -m pip install -r requirements.txt
```

Expected: pip reports `Successfully installed ...` for `pymupdf`, `pytesseract`, `Pillow`, `pytest` (or "already satisfied").

- [ ] **Step 3: Install the Tesseract OCR binary (guided, one-time)**

This one needs a graphical installer, not pip. Walk James through this in the chat, step by step:
1. Open a browser and go to `https://github.com/UB-Mannheim/tesseract/wiki` (the standard Windows build of Tesseract).
2. Download the latest `tesseract-ocr-w64-setup-*.exe` installer.
3. Run the installer, keep the default install location (`C:\Program Files\Tesseract-OCR`).
4. After install, add `C:\Program Files\Tesseract-OCR` to the Windows PATH: Windows key → type "environment variables" → "Edit the system environment variables" → "Environment Variables" button → under "User variables", select `Path` → "Edit" → "New" → paste `C:\Program Files\Tesseract-OCR` → OK on every dialog.
5. Close and reopen any open terminal (Git Bash included) so it picks up the new PATH.

- [ ] **Step 4: Write the environment smoke test**

```python
# tests/test_environment.py
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
```

- [ ] **Step 5: Run the smoke test**

Run: `python -m pytest tests/test_environment.py -v`
Expected: 3 passed. If `test_tesseract_binary_on_path` or `test_pytesseract_can_reach_tesseract` fails, stop and fix Step 3 (reopen the terminal, double check the PATH entry) before continuing to Task 2.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt tests/test_environment.py
git commit -m "Add prerequisites and environment smoke test"
```

---

## Task 2: Cache path and metadata helpers

**Files:**
- Create: `C:\Users\jklel\CLAUDE\pdf-to-md\convert.py`
- Test: `C:\Users\jklel\CLAUDE\pdf-to-md\tests\test_convert.py`

**Interfaces:**
- Produces:
  - `cache_paths(pdf_path: Path) -> tuple[Path, Path]` — returns `(md_path, meta_path)`.
  - `load_meta(meta_path: Path) -> dict` — `{}` if the file doesn't exist.
  - `save_meta(meta_path: Path, data: dict) -> None`.
  - `is_cache_valid(pdf_path: Path, meta: dict) -> bool`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_convert.py
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_convert.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'convert'` (the file doesn't exist yet).

- [ ] **Step 3: Write the minimal implementation**

```python
# convert.py
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convert.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add convert.py tests/test_convert.py
git commit -m "Add PDF conversion cache path and metadata helpers"
```

---

## Task 3: Direct text extraction

**Files:**
- Modify: `C:\Users\jklel\CLAUDE\pdf-to-md\convert.py`
- Test: `C:\Users\jklel\CLAUDE\pdf-to-md\tests\test_convert.py`

**Interfaces:**
- Consumes: nothing from Task 2 directly.
- Produces: `extract_text_pdf(pdf_path: Path) -> str | None` — returns the extracted text joined across pages if average chars/page > `TEXT_CHARS_PER_PAGE_THRESHOLD` (40), else `None`. Also defines the module-level constant `TEXT_CHARS_PER_PAGE_THRESHOLD = 40`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_convert.py
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_convert.py -v -k extract_text_pdf`
Expected: FAIL — `AttributeError: module 'convert' has no attribute 'extract_text_pdf'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# add to convert.py, after the imports
import fitz

TEXT_CHARS_PER_PAGE_THRESHOLD = 40


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convert.py -v -k extract_text_pdf`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add convert.py tests/test_convert.py
git commit -m "Add direct text extraction for real-text PDFs"
```

---

## Task 4: OCR extraction with confidence scoring

**Files:**
- Modify: `C:\Users\jklel\CLAUDE\pdf-to-md\convert.py`
- Test: `C:\Users\jklel\CLAUDE\pdf-to-md\tests\test_convert.py`

**Interfaces:**
- Produces: `ocr_pdf(pdf_path: Path) -> tuple[str, float]` — returns `(extracted_text, average_confidence_0_to_100)`. Also defines `OCR_CONFIDENCE_THRESHOLD = 70.0`.
- These tests monkeypatch `pytesseract.image_to_data` so the confidence math is tested deterministically, independent of actual OCR accuracy (real-world OCR quality is covered by the manual test matrix in Task 8).

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_convert.py
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_convert.py -v -k ocr_pdf`
Expected: FAIL — `AttributeError: module 'convert' has no attribute 'ocr_pdf'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# add to convert.py, after the extract_text_pdf function
import io

import pytesseract
from PIL import Image

OCR_CONFIDENCE_THRESHOLD = 70.0


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convert.py -v -k ocr_pdf`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add convert.py tests/test_convert.py
git commit -m "Add OCR extraction with Tesseract confidence scoring"
```

---

## Task 5: Orchestrator — full decision logic with cache and failure tracking

**Files:**
- Modify: `C:\Users\jklel\CLAUDE\pdf-to-md\convert.py`
- Test: `C:\Users\jklel\CLAUDE\pdf-to-md\tests\test_convert.py`

**Interfaces:**
- Consumes: `cache_paths`, `load_meta`, `save_meta`, `is_cache_valid` (Task 2); `extract_text_pdf`, `TEXT_CHARS_PER_PAGE_THRESHOLD` (Task 3); `ocr_pdf`, `OCR_CONFIDENCE_THRESHOLD` (Task 4).
- Produces:
  - `ConversionResult` dataclass with fields `outcome: str` (`"redirect"` or `"allow"`), `md_path: Path | None`, `message: str`.
  - `convert(pdf_path: Path) -> ConversionResult` — the full decision logic (cache reuse → text extraction → OCR → allow-through). Raises whatever exception the underlying extraction/OCR call raised; does not catch anything itself (Task 6's `hook.py` is the layer that catches and manages the failure counter).
  - `record_failure(meta_path: Path) -> int` — increments and persists `fail_count` in the metadata sidecar, returns the new count.
  - `reset_failure(meta_path: Path) -> None` — sets `fail_count` back to 0 if it was set.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_convert.py
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_convert.py -v -k "convert_ or record_failure or reset_failure"`
Expected: FAIL — `AttributeError: module 'convert' has no attribute 'convert'` (and similarly for `record_failure`/`reset_failure`).

- [ ] **Step 3: Write the minimal implementation**

```python
# add to convert.py, after the ocr_pdf function
from dataclasses import dataclass


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_convert.py -v`
Expected: all tests in the file pass (16 tests total across Tasks 2-5).

- [ ] **Step 5: Commit**

```bash
git add convert.py tests/test_convert.py
git commit -m "Add convert() orchestrator with caching and failure tracking"
```

---

## Task 6: The `PreToolUse` hook entry point

**Files:**
- Create: `C:\Users\jklel\CLAUDE\pdf-to-md\hook.py`
- Test: `C:\Users\jklel\CLAUDE\pdf-to-md\tests\test_hook.py`

**Interfaces:**
- Consumes: `convert.convert`, `convert.cache_paths`, `convert.record_failure`, `convert.reset_failure` (Task 5).
- Produces: a script invocable as `python hook.py`, reading a JSON payload on stdin (shape: `{"tool_name": str, "tool_input": {"file_path": str}}`) and writing one JSON line to stdout, shaped as `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny"|"allow", "permissionDecisionReason": str}}`. Exits 0 in every case (never blocks Claude Code itself, even on an internal crash).
- These tests invoke `hook.py` as a subprocess (the same way Claude Code will) rather than importing it, so they exercise the real stdin/stdout contract.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hook.py
import json
import subprocess
import sys
from pathlib import Path

HOOK_PATH = Path(__file__).parent.parent / "hook.py"


def run_hook(payload: dict) -> dict:
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_hook_ignores_non_read_tools():
    output = run_hook({"tool_name": "Write", "tool_input": {"file_path": "x.pdf"}})
    assert output == {}


def test_hook_ignores_non_pdf_reads(tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("hello", encoding="utf-8")
    output = run_hook({"tool_name": "Read", "tool_input": {"file_path": str(target)}})
    assert output == {}


def test_hook_denies_and_redirects_text_pdf(tmp_path):
    import fitz

    pdf_path = tmp_path / "contrato.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Contrato de prestacao de servicos. " * 10, fontsize=12)
    doc.save(pdf_path)
    doc.close()

    output = run_hook({"tool_name": "Read", "tool_input": {"file_path": str(pdf_path)}})

    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    md_path = tmp_path / ".pdf-cache" / "contrato.md"
    assert str(md_path) in output["hookSpecificOutput"]["permissionDecisionReason"]
    assert md_path.exists()


def test_hook_blocks_with_reason_on_first_failure_then_allows_on_second(tmp_path):
    missing_pdf = tmp_path / "nao_existe.pdf"

    first = run_hook({"tool_name": "Read", "tool_input": {"file_path": str(missing_pdf)}})
    assert first["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "1" in first["hookSpecificOutput"]["permissionDecisionReason"] or "tentativa" in (
        first["hookSpecificOutput"]["permissionDecisionReason"].lower()
    )

    second = run_hook({"tool_name": "Read", "tool_input": {"file_path": str(missing_pdf)}})
    assert second["hookSpecificOutput"]["permissionDecision"] == "allow"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_hook.py -v`
Expected: FAIL — `hook.py` does not exist, subprocess call fails with a non-zero exit / `FileNotFoundError`.

- [ ] **Step 3: Write the minimal implementation**

```python
# hook.py
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import convert as conv  # noqa: E402


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0

    if payload.get("tool_name") != "Read":
        _emit({})
        return 0

    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path.lower().endswith(".pdf"):
        _emit({})
        return 0

    pdf_path = Path(file_path)
    _, meta_path = conv.cache_paths(pdf_path)

    try:
        result = conv.convert(pdf_path)
    except Exception as exc:  # noqa: BLE001 - must never crash the hook
        fail_count = conv.record_failure(meta_path)
        if fail_count <= 1:
            _emit_decision(
                "deny",
                f"Falha ao converter PDF para markdown (tentativa {fail_count}): {exc}. "
                "Corrija o problema (ex: instalar dependencia) e peca para ler o PDF de novo.",
            )
        else:
            conv.reset_failure(meta_path)
            _emit_decision(
                "allow",
                f"Conversao falhou novamente ({exc}); lendo o PDF original como ultimo recurso "
                "por causa de um erro de ferramenta nao resolvido.",
            )
        return 0

    if result.outcome == "redirect":
        _emit_decision(
            "deny",
            f"PDF convertido para markdown em {result.md_path}. Leia esse arquivo em vez do PDF original.",
        )
    else:
        _emit_decision("allow", result.message)
    return 0


def _emit_decision(decision: str, reason: str) -> None:
    _emit(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        }
    )


def _emit(payload: dict) -> None:
    print(json.dumps(payload))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - last-resort fail-open safety net
        print(f"pdf-to-md hook crashed unexpectedly: {exc}", file=sys.stderr)
        sys.exit(0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_hook.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest -v`
Expected: all tests across `test_environment.py`, `test_convert.py`, and `test_hook.py` pass.

- [ ] **Step 6: Commit**

```bash
git add hook.py tests/test_hook.py
git commit -m "Add PreToolUse hook entry point wrapping convert.py"
```

---

## Task 7: Register the hook globally and verify it fires

**Files:**
- Modify: `C:\Users\jklel\.claude\settings.json`

**Interfaces:**
- Consumes: `hook.py` (Task 6) as a subprocess target.

- [ ] **Step 1: Read the current global settings file**

Run: `python -c "import json,sys; print(json.dumps(json.load(open(r'C:\Users\jklel\.claude\settings.json')), indent=2))" 2>&1 || echo "file may not exist yet"`

If it doesn't exist, treat the merge target as `{}`.

- [ ] **Step 2: Merge in the hook registration**

Add (merging with whatever `hooks` and other top-level keys already exist — do not replace the file):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          {
            "type": "command",
            "command": "python",
            "args": ["C:\\Users\\jklel\\CLAUDE\\pdf-to-md\\hook.py"],
            "timeout": 120
          }
        ]
      }
    ]
  }
}
```

Use the `args` form (not a shell string) so no shell-quoting issues arise on Windows.

- [ ] **Step 3: Validate the JSON syntax and structure**

Run:

```bash
jq -e '.hooks.PreToolUse[] | select(.matcher == "Read") | .hooks[] | select(.type == "command") | .command' "C:\Users\jklel\.claude\settings.json"
```

Expected: exit 0, prints `"python"`.

- [ ] **Step 4: Pipe-test the raw hook command**

```bash
echo '{"tool_name":"Read","tool_input":{"file_path":"C:/Users/jklel/CLAUDE/pdf-to-md/tests/does_not_exist.pdf"}}' | python "C:/Users/jklel/CLAUDE/pdf-to-md/hook.py"
```

Expected: one line of JSON on stdout with `"permissionDecision": "deny"` and a reason mentioning attempt 1.

- [ ] **Step 5: Tell James to reload hooks**

Since this is the first hook registered for this settings file, the running Claude Code session's file watcher may not pick it up automatically. Tell James: "Hooks alterados — para ativar, digite `/hooks` uma vez nesta janela do Claude Code, ou feche e abra uma nova janela." Do not attempt to run `/hooks` yourself — it's an interactive menu.

- [ ] **Step 6: Commit**

The settings file lives outside this project's git repo (`~/.claude/settings.json`), so there is nothing to commit here. Instead, verify: ask James to open a **new** Claude Code session in any folder, then in that new session ask it to read a real PDF file and confirm it gets redirected to a `.md` file instead.

---

## Task 8: End-to-end manual verification (the spec's test matrix)

**Files:** none (manual verification using files created ad hoc under a scratch folder).

**Interfaces:** none — this task exercises the whole system through the real Claude Code hook path, not through pytest.

- [ ] **Step 1: Text-based PDF**

Ask James for (or create) a simple text PDF. Try to read it via a fresh Claude Code session. Confirm: the session's transcript shows the Read being redirected, `.pdf-cache/<name>.md` appears next to the PDF with correct text.

- [ ] **Step 2: Good-quality scanned PDF**

Use a clear, well-scanned PDF (a printed page photographed straight-on works). Confirm: OCR path triggers, `.pdf-cache/<name>.md` is created with mostly-correct text, average confidence was high enough to redirect (no fallback to raw PDF).

- [ ] **Step 3: Poor-quality/rotated scanned PDF**

Use a blurry or rotated scan. Confirm: the hook allows the original Read through unmodified — Claude reads the raw PDF exactly as it did before this project existed.

- [ ] **Step 4: Simulated missing dependency**

Temporarily rename `C:\Program Files\Tesseract-OCR\tesseract.exe` to `tesseract.exe.bak`. Try reading a scanned PDF (that isn't already cached). Confirm: 1st attempt is denied with a clear error reason naming the problem. Retry the same read. Confirm: 2nd attempt is allowed through, with a message noting the unresolved error. Rename the file back to `tesseract.exe` afterward.

- [ ] **Step 5: Re-read the same unchanged PDF**

Read the same PDF from Step 1 again in a new turn. Confirm: no reconversion happens (check the `.md` file's modified timestamp doesn't change) — the cached version is reused.

- [ ] **Step 6: Edit the PDF and re-read**

Touch or modify the PDF from Step 1 (even just resaving it) so its size or mtime changes. Read it again. Confirm: the cache is invalidated and reconversion happens (new `.md` content/timestamp).

- [ ] **Step 7: Non-PDF file**

Read any `.txt` or `.md` file. Confirm: nothing about the read is different from before this project existed (no denial, no cache folder created).

- [ ] **Step 8: Report results to James**

Summarize which of the 7 scenarios passed. If any failed, go back to systematic-debugging on the specific failing piece before considering this plan complete.
