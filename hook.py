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
