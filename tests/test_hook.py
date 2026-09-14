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
