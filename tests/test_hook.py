import io
import json
import os
import subprocess
import sys
from pathlib import Path

HOOK_PATH = Path(__file__).parent.parent / "hook.py"


def run_hook(payload: dict) -> dict:
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout.decode("utf-8"))


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
    # PDF existente mas ilegivel: a conversao falha de verdade (caminho inexistente
    # agora e barrado antes, sem criar pastas - ver test_hook_allows_nonexistent_path...).
    missing_pdf = tmp_path / "corrompido.pdf"
    missing_pdf.write_bytes(b"isto nao e um pdf")

    first = run_hook({"tool_name": "Read", "tool_input": {"file_path": str(missing_pdf)}})
    assert first["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "1" in first["hookSpecificOutput"]["permissionDecisionReason"] or "tentativa" in (
        first["hookSpecificOutput"]["permissionDecisionReason"].lower()
    )

    second = run_hook({"tool_name": "Read", "tool_input": {"file_path": str(missing_pdf)}})
    assert second["hookSpecificOutput"]["permissionDecision"] == "allow"


def test_hook_handles_accented_paths_correctly(tmp_path):
    accented_dir = tmp_path / "Documentação"
    accented_dir.mkdir()
    missing_pdf = accented_dir / "Não_existe.pdf"

    output = run_hook({"tool_name": "Read", "tool_input": {"file_path": str(missing_pdf)}})

    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert str(missing_pdf) in reason


# --- Payload em UTF-8 real (o Claude Code manda bytes UTF-8; o stdin do Windows e cp1252) ---

MOJIBAKE_MARKERS = ("Ã", "Â")  # "Ã" / "Â" de UTF-8 lido como cp1252


def _make_accented_pdf(tmp_path):
    import pymupdf as fitz  # 'import fitz' imprime um aviso de depreciacao no stdout

    folder = tmp_path / "Terceirização" / "Documentação para análise"
    folder.mkdir(parents=True)
    pdf_path = folder / "x.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Folha de pagamento de agosto. " * 10, fontsize=12)
    doc.save(pdf_path)
    doc.close()
    return pdf_path


def _run_main_with_windows_stdin(monkeypatch, capsys, payload_bytes: bytes):
    """Chama hook.main() com um stdin que imita o Windows: o wrapper de texto decodifica
    em cp1252 (sys.stdin.read() daria mojibake), mas .buffer guarda os bytes UTF-8 reais."""
    monkeypatch.syspath_prepend(str(HOOK_PATH.parent))
    import hook

    fake_stdin = io.TextIOWrapper(io.BytesIO(payload_bytes), encoding="cp1252")
    monkeypatch.setattr(sys, "stdin", fake_stdin)
    code = hook.main()
    return code, capsys.readouterr().out


def _no_mojibake_names(root):
    return [p for p in root.rglob("*") if any(m in p.name for m in MOJIBAKE_MARKERS)]


def test_hook_main_reads_utf8_payload_despite_cp1252_stdin(tmp_path, monkeypatch, capsys):
    pdf_path = _make_accented_pdf(tmp_path)
    payload = {"tool_name": "Read", "tool_input": {"file_path": str(pdf_path)}}
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    code, out = _run_main_with_windows_stdin(monkeypatch, capsys, raw)

    assert code == 0
    output = json.loads(out)
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    md_path = pdf_path.parent / ".pdf-cache" / "x.md"
    assert md_path.exists()
    assert str(md_path) in output["hookSpecificOutput"]["permissionDecisionReason"]
    assert _no_mojibake_names(tmp_path) == []


def test_hook_subprocess_reads_utf8_payload_with_cp1252_stdin(tmp_path):
    pdf_path = _make_accented_pdf(tmp_path)
    payload = {"tool_name": "Read", "tool_input": {"file_path": str(pdf_path)}}
    env = {**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"}
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        capture_output=True,
        check=True,
        env=env,
    )

    output = json.loads(result.stdout.decode("utf-8"))
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert (pdf_path.parent / ".pdf-cache" / "x.md").exists()
    assert _no_mojibake_names(tmp_path) == []


def test_hook_allows_nonexistent_path_without_creating_directories(tmp_path):
    missing_pdf = tmp_path / "Terceirização" / "Documentação" / "Não_existe.pdf"

    output = run_hook({"tool_name": "Read", "tool_input": {"file_path": str(missing_pdf)}})

    assert output["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert str(missing_pdf) in output["hookSpecificOutput"]["permissionDecisionReason"]
    assert list(tmp_path.iterdir()) == []


def test_hook_exits_silently_on_invalid_json_or_invalid_utf8(monkeypatch, capsys):
    invalid_utf8 = b'{"tool_name": "' + bytes([0xFF, 0xFE]) + b'"}'
    for raw in (b"{isto nao e json", invalid_utf8):
        code, out = _run_main_with_windows_stdin(monkeypatch, capsys, raw)
        assert code == 0
        assert out == ""
