# PDF → Markdown auto-conversion hook — design spec

Date: 2026-09-13
Status: Approved by user, ready for implementation plan

## Problem

Reading a PDF in a Claude Code conversation is much more expensive in
tokens than reading equivalent plain text, because each page is sent
as an image. James wants PDFs converted to lean text/markdown
automatically, every time, without having to ask — but never at the
cost of an unexpected Anthropic API bill, and never in a way that
silently hides a broken setup from him.

## Scope

- Applies only inside Claude Code, running locally on this Windows
  machine. Does **not** affect PDFs uploaded directly on claude.ai
  (no hook mechanism exists there).
- Applies to every project/session on this machine (global hook), not
  just this folder.
- Triggers specifically when Claude (via the `Read` tool) tries to
  read a file whose path ends in `.pdf` (case-insensitive).

## Non-goals

- No separate Anthropic API key / billing account. The one path that
  needs an LLM to read a hard scanned PDF reuses the *current*
  Claude Code conversation's own reading of the file — it is not a
  background API call.
- No cloud OCR services. Tesseract runs fully locally.
- No support for non-PDF formats in this project.

## Components

1. **`convert.py`** — the conversion pipeline. Pure function library,
   independently testable, no hook-specific code.
2. **`hook.py`** — the Claude Code `PreToolUse` hook entry point. Reads
   the hook JSON payload from stdin, decides whether to intervene,
   calls into `convert.py`, and writes the hook JSON decision to
   stdout.
3. **`~/.claude/settings.json`** registration — wires `hook.py` to
   fire on `PreToolUse` for the `Read` tool, globally (user settings,
   not project settings, so it applies everywhere).
4. **Cache directory** — `.pdf-cache/` created next to each PDF that
   gets converted, holding the generated `.md` and a small sidecar
   metadata file (`<name>.meta.json`) tracking source size, mtime, and
   consecutive-failure count.

## Decision logic (per PDF read attempt)

```
1. Compute a cache key from the PDF's size + mtime.
   - If .pdf-cache/<name>.md exists and its metadata matches the
     current size+mtime → reuse it, skip straight to "redirect".
2. Try direct text extraction (PyMuPDF / fitz).
   - If the average extracted characters per page is above a
     threshold (40 chars/page) → treat as a real text PDF.
   - Write the extracted text as .pdf-cache/<name>.md.
   - Reset failure count to 0. → redirect.
3. Otherwise, treat as scanned/image PDF: render each page to an
   image (PyMuPDF get_pixmap, no Poppler dependency) and run
   pytesseract OCR on each page.
   - Collect Tesseract's per-word confidence values; compute the
     average confidence across the whole document.
   - If average confidence >= 70 → accept the OCR text, write it as
     .pdf-cache/<name>.md, reset failure count to 0. → redirect.
   - If average confidence < 70 → OCR quality inadequate. This is
     NOT an error — it's an expected outcome. → allow (do not
     redirect; let Claude read the original PDF in the current
     conversation, as it does today).
4. If any step above raises an exception (missing dependency, import
   error, Tesseract not found or misconfigured, corrupt PDF, etc.):
   - Read the current failure count from the metadata sidecar
     (0 if none).
   - If failure count == 0: increment to 1, persist it, and BLOCK the
     Read with a reason string containing the exact exception
     message and a short hint (e.g. "pytesseract not installed / not
     on PATH"). This surfaces the problem to Claude and James in the
     conversation so they can fix it together. Do not fall back yet.
   - If failure count >= 1 (i.e. this is the second consecutive
     failure for this same PDF): allow the original Read to proceed
     as a last resort, but the hook's stdout message says clearly
     that this is a fallback due to an unresolved tool error, not a
     normal decision. Reset the failure count back to 0 afterward so
     the next attempt on this file starts fresh.

"→ redirect" means: BLOCK the original Read tool call, with a reason
telling Claude the converted markdown is available at
`.pdf-cache/<name>.md` and to read that file instead.
```

## Error handling details

- All exceptions in `convert.py` are caught in `hook.py`; nothing
  should crash the hook process itself (a crashing hook with no valid
  JSON output could block Claude Code from working at all). Any truly
  unexpected top-level exception in `hook.py` itself falls back to
  "allow" immediately (fail open), after printing a warning to
  stderr — this is a last-resort safety net distinct from the
  documented convert.py failure-count flow above.
- The failure counter is per-file (keyed by absolute path in the
  metadata sidecar), so unrelated PDFs are unaffected by one broken
  file, and a fixed dependency clears itself on the next fresh PDF
  automatically (only a file that has already failed once carries a
  counter).

## Testing plan

Manual test matrix (no existing automated test infra for hooks in
Claude Code, so this is exercised by hand):

1. Text-based PDF → verify `.pdf-cache/<name>.md` is created with
   correct extracted text, and Claude reads the `.md` not the PDF.
2. Good-quality scanned PDF → verify OCR path triggers, confidence
   is high, `.md` is created with reasonable OCR text.
3. Poor-quality/rotated scanned PDF → verify OCR path triggers,
   confidence is low, hook allows the original Read through
   unmodified (Claude reads the raw PDF as it does today).
4. Simulate a missing dependency (e.g. temporarily rename the
   tesseract executable) → first Read attempt is blocked with a clear
   error reason; second consecutive attempt on the same file falls
   back to normal Read with a visible warning.
5. Re-read the same unchanged PDF a second time → verify the cached
   `.md` is reused without re-running extraction/OCR (fast path).
6. Edit/replace the PDF (change mtime/size) → verify the cache is
   invalidated and reconversion happens.
7. Non-PDF file read → verify the hook does not interfere at all.

## Installation prerequisites (one-time, user's machine)

- Python 3 (with `pip`)
- Python packages: `pymupdf`, `pytesseract`
- Tesseract OCR binary installed and on PATH (Windows installer)

These will be walked through step-by-step with James during
implementation, since he is not comfortable with command-line tooling
on his own — installer downloads and exact Git Bash commands to paste.
