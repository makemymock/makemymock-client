"""Deterministic LaTeX / math cleanup for SolverX block content.

Runs at block-emit time on every text-bearing block. Operates in
microseconds, costs nothing, and catches the most common rendering
issues the deep solver produces:

    1. Unicode minus  −  → ASCII minus  -        (anywhere — always safe)
    2. Other Unicode math symbols (≈, ×, π, Ω, …) → LaTeX equivalents,
       but ONLY when they sit inside an existing $...$ math region.
       Casual use of these characters in prose is left alone.
    3. Bare `\\command` tokens (and the full math expression around
       them — operators, args, subscripts) get wrapped in $...$ so
       KaTeX renders them. Brace-counting parser, so the nested
       braces in things like \\frac{n_{lens}}{v_1} are handled
       correctly.

The LLM polish agent picks up cases this misses — broken delimiter
pairing, multi-character subscripts that need braces, unit glue, etc.
This module's only job is the fast deterministic floor.
"""

from __future__ import annotations

import re


# Unicode → LaTeX. Applied either:
#   • always, when the symbol is ASCII-safe in prose too (just the minus)
#   • only inside $...$, when the symbol could appear casually in English
_UNICODE_ALWAYS_SAFE = {
    "−": "-",          # − minus
}

_UNICODE_INSIDE_MATH = {
    "≈": r"\approx",
    "×": r"\times",
    "÷": r"\div",
    "±": r"\pm",
    "∓": r"\mp",
    "≤": r"\le",
    "≥": r"\ge",
    "≠": r"\ne",
    "∞": r"\infty",
    "°": r"^\circ",
    "∘": r"^\circ",
    "⋅": r"\cdot",
    "→": r"\to",
    "⇒": r"\Rightarrow",
    "∴": r"\therefore",
    "∵": r"\because",
    # Greek lowercase
    "α": r"\alpha",  "β": r"\beta",   "γ": r"\gamma",  "δ": r"\delta",
    "ε": r"\varepsilon", "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta",
    "ι": r"\iota",   "κ": r"\kappa",  "λ": r"\lambda", "μ": r"\mu",
    "ν": r"\nu",     "ξ": r"\xi",     "π": r"\pi",     "ρ": r"\rho",
    "σ": r"\sigma",  "τ": r"\tau",    "υ": r"\upsilon", "φ": r"\varphi",
    "χ": r"\chi",    "ψ": r"\psi",    "ω": r"\omega",
    # Greek uppercase (only the ones with distinct glyphs)
    "Γ": r"\Gamma",  "Δ": r"\Delta",  "Θ": r"\Theta",  "Λ": r"\Lambda",
    "Ξ": r"\Xi",     "Π": r"\Pi",     "Σ": r"\Sigma",  "Φ": r"\Phi",
    "Ψ": r"\Psi",    "Ω": r"\Omega",
}


# Matches existing math regions: $$...$$ block then $...$ inline. Order
# matters — $$ has to be tested first or we'd partially eat it.
_MATH_REGION_RE = re.compile(r"(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)")


# Characters that may appear between math tokens without breaking the run.
_MATH_GLUE = set("=+-*/^_<>(),.[]| ")


def _normalize_inside_math(text: str) -> str:
    """Apply the inside-math Unicode→LaTeX replacements to a span that
    is already known to be a math region."""
    for uni, latex in _UNICODE_INSIDE_MATH.items():
        if uni in text:
            text = text.replace(uni, latex)
    return text


def _walk_balanced_brace(s: str, start: int) -> int:
    """Given s[start] == '{', return the index AFTER the matching '}'.
    Returns -1 if unbalanced (no matching close brace found)."""
    if start >= len(s) or s[start] != "{":
        return -1
    depth = 1
    pos = start + 1
    while pos < len(s):
        c = s[pos]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return -1


def _scan_command_token(s: str, start: int) -> int:
    """Given s[start] == '\\' followed by an alpha character, scan to the
    end of one `\\command{...}{...}_{...}^{...}` token (including all
    its arguments). Returns position AFTER the token."""
    if start >= len(s) or s[start] != "\\":
        return start
    pos = start + 1
    # Command name (alpha chars).
    while pos < len(s) and s[pos].isalpha():
        pos += 1
    # Suffixes: any number of `{...}`, `_x`, `^x`, `_{...}`, `^{...}`.
    while pos < len(s):
        c = s[pos]
        if c == "{":
            end = _walk_balanced_brace(s, pos)
            if end == -1:
                return pos
            pos = end
        elif c in ("_", "^"):
            if pos + 1 >= len(s):
                return pos
            nxt = s[pos + 1]
            if nxt == "{":
                end = _walk_balanced_brace(s, pos + 1)
                if end == -1:
                    return pos
                pos = end
            elif nxt.isalnum() or nxt == "\\":
                # Single-character subscript/superscript, OR another
                # \command following the operator.
                pos += 2 if nxt != "\\" else 1
                if nxt == "\\":
                    pos = _scan_command_token(s, pos - 1)
            else:
                return pos
        else:
            return pos
    return pos


def _extend_math_run(s: str, run_start: int, run_end: int) -> int:
    """A `\\command{...}` token ended at `run_end`. Extend the math run
    forward through any glue-operators / single-letter variables /
    digits / nested `\\command` tokens, stopping when we hit prose.

    "Prose" heuristic: an alpha word of 3+ characters that does NOT
    start with `\\` and is not a recognised single-letter math variable
    immediately followed by an operator.
    """
    pos = run_end
    n = len(s)
    while pos < n:
        c = s[pos]

        # Math glue (operators, spaces, punctuation) — keep going.
        if c in _MATH_GLUE:
            # Disallow consecutive newlines — that's a hard paragraph
            # break and definitely ends the math run.
            if c == " " and pos + 1 < n and s[pos + 1] == " ":
                # Two spaces in a row usually means a hard line break in
                # markdown — be safe and stop.
                return pos
            pos += 1
            continue

        if c == "\n":
            # Newlines break the run unless the next char is more math.
            return pos

        if c == "{":
            end = _walk_balanced_brace(s, pos)
            if end == -1:
                return pos
            pos = end
            continue

        # Another \command — extend through it recursively.
        if c == "\\" and pos + 1 < n and s[pos + 1].isalpha():
            new_end = _scan_command_token(s, pos)
            if new_end == pos:
                return pos
            pos = new_end
            continue

        # Digits + dot for numbers.
        if c.isdigit() or c == ".":
            while pos < n and (s[pos].isdigit() or s[pos] == "."):
                pos += 1
            continue

        # Single letter — variable. Allowed.
        if c.isalpha():
            word_start = pos
            while pos < n and s[pos].isalpha():
                pos += 1
            word_len = pos - word_start
            if word_len >= 3:
                # Looks like prose — back up to start of word and stop.
                return word_start
            # 1–2 letters: math variable. Keep going.
            continue

        # Anything else: stop.
        return pos

    return pos


def _find_math_runs(s: str, skip_spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Find every contiguous math run in `s` that should be wrapped in
    $...$. Skips ranges in `skip_spans` (existing $...$ regions)."""
    runs: list[tuple[int, int]] = []
    i = 0
    n = len(s)

    def in_skip(pos: int) -> bool:
        for a, b in skip_spans:
            if a <= pos < b:
                return True
        return False

    while i < n - 1:
        if s[i] == "\\" and s[i + 1].isalpha() and not in_skip(i):
            # Found the start of a bare \command. Walk through this
            # token, then extend the run forward through math glue.
            tok_end = _scan_command_token(s, i)
            run_end = _extend_math_run(s, i, tok_end)
            # Skip pure-whitespace at the tail.
            while run_end > i and s[run_end - 1].isspace():
                run_end -= 1
            if run_end > i:
                runs.append((i, run_end))
                i = run_end
                continue
        i += 1
    return runs


def normalize_latex_block(content: str) -> str:
    """Best-effort deterministic cleanup of LaTeX/math in markdown.

    Safe to call on EVERY emitted block — O(n) and adds microseconds.
    Returns `content` unchanged when nothing needs fixing.
    """
    if not content:
        return content

    # ---- Pass 1a — ASCII-fy Unicode minus everywhere. ----
    for uni, ascii_repl in _UNICODE_ALWAYS_SAFE.items():
        if uni in content:
            content = content.replace(uni, ascii_repl)

    # ---- Pass 1b — Normalize Unicode math symbols inside $...$ only. ----
    def _on_math_region(m: re.Match) -> str:
        return _normalize_inside_math(m.group(0))

    content = _MATH_REGION_RE.sub(_on_math_region, content)

    # ---- Pass 2 — Wrap bare math runs in $...$. ----
    skip_spans = [(m.start(), m.end()) for m in _MATH_REGION_RE.finditer(content)]
    runs = _find_math_runs(content, skip_spans)
    if not runs:
        return content

    # Apply wraps in reverse so the indices don't shift.
    out = content
    for start, end in reversed(runs):
        # Strip trailing punctuation that shouldn't be inside math
        # (e.g. trailing period meant as sentence end).
        run_text = out[start:end]
        trailing = ""
        while run_text and run_text[-1] in {".", ","}:
            # Only treat as sentence punctuation if followed by a space
            # or end-of-string in the surrounding context.
            after = out[end : end + 1]
            if after in ("", " ", "\n"):
                trailing = run_text[-1] + trailing
                run_text = run_text[:-1]
                end -= 1
            else:
                break
        wrapped = f"${run_text.strip()}$"
        out = out[:start] + wrapped + trailing + out[end:]

    return out
