from __future__ import annotations

import contextlib
import os
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import convert as conv  # noqa: E402


@contextlib.contextmanager
def _suppress_stdout():
    """Silence anything convert.py's dependencies print to the real stdout
    file descriptor (not just sys.stdout), so it never corrupts the hook's
    single-line JSON output contract."""
    sys.stdout.flush()
    saved_fd = os.dup(1)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(saved_fd, 1)
        os.close(devnull_fd)
        os.close(saved_fd)


def main() -> int:
    try:
        # O Claude Code manda o payload como bytes UTF-8, mas no Windows sys.stdin
        # decodifica com a code page do console (cp1252): "Terceirização" viraria
        # "TerceirizaÃ§Ã£o". Por isso lemos os bytes crus e decodificamos como UTF-8.
        # "utf-8-sig" tolera um BOM eventual. Se os bytes nao forem UTF-8 valido, nao
        # ha como confiar no caminho (com errors="replace" o caminho viraria outro):
        # trata como payload ilegivel, igual a JSON invalido (sai com 0, sem saida).
        raw = sys.stdin.buffer.read().decode("utf-8-sig")
        payload = json.loads(raw) if raw.strip() else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 0

    if payload.get("tool_name") != "Read":
        _emit({})
        return 0

    file_path = payload.get("tool_input", {}).get("file_path", "")
    if not file_path.lower().endswith(".pdf"):
        _emit({})
        return 0

    pdf_path = Path(file_path)
    if not pdf_path.is_file():
        # Guarda: caminho inexistente nao e convertido nem gera pastas (record_failure/
        # _write_conversion fariam mkdir de toda a arvore .pdf-cache). Libera a leitura:
        # a ferramenta Read mostra o erro real de arquivo nao encontrado.
        _emit_decision(
            "allow",
            f"Arquivo PDF nao encontrado: {file_path}; nada a converter, "
            "deixando a leitura original seguir.",
        )
        return 0
    _, meta_path = conv.cache_paths(pdf_path)

    try:
        with _suppress_stdout():
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
    # ensure_ascii=True (padrao): a saida e ASCII puro (acentos viram \uXXXX), entao
    # nenhuma code page do stdout do Windows consegue corromper caminhos acentuados.
    print(json.dumps(payload))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - last-resort fail-open safety net
        print(f"pdf-to-md hook crashed unexpectedly: {exc}", file=sys.stderr)
        sys.exit(0)
