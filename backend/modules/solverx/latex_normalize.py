"""Deterministic LaTeX / math cleanup for SolverX block content.

Runs at block-emit time on every text-bearing block. Operates in
microseconds, costs nothing, and catches the most common rendering
issues the deep solver produces:

    1. Unicode minus  −  → ASCII minus  -        (anywhere — always safe)
    2. Other Unicode math symbols (≈, ×, π, Ω, …) → LaTeX equivalents,
       but ONLY when they sit inside an existing $...$ math region.
       Casual use of these characters in prose is left alone.
    3. Bare `\\command` tokens outside math regions get wrapped in
       $...$ so KaTeX renders them. (`\\omega_0` in prose becomes
       `$\\omega_0$`.)

The LLM-based polish agent picks up cases this misses — broken
delimiter pairing, mixed prose+math equations, multi-character
subscripts that need braces, etc. This module's only job is the
fast deterministic floor.
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
    "≈": r"\approx",   # ≈
    "×": r"\times",    # ×
    "÷": r"\div",      # ÷
    "±": r"\pm",       # ±
    "∓": r"\mp",       # ∓
    "≤": r"\le",       # ≤
    "≥": r"\ge",       # ≥
    "≠": r"\ne",       # ≠
    "∞": r"\infty",    # ∞
    "°": r"^\circ",    # ° degree
    "∘": r"^\circ",    # ∘ (some models use this instead)
    "⋅": r"\cdot",     # ⋅
    "→": r"\to",       # →
    "⇒": r"\Rightarrow",  # ⇒
    "∴": r"\therefore",   # ∴
    "∵": r"\because",     # ∵
    # Greek lowercase
    "α": r"\alpha",    # α
    "β": r"\beta",     # β
    "γ": r"\gamma",    # γ
    "δ": r"\delta",    # δ
    "ε": r"\varepsilon",  # ε
    "ζ": r"\zeta",     # ζ
    "η": r"\eta",      # η
    "θ": r"\theta",    # θ
    "ι": r"\iota",     # ι
    "κ": r"\kappa",    # κ
    "λ": r"\lambda",   # λ
    "μ": r"\mu",       # μ
    "ν": r"\nu",       # ν
    "ξ": r"\xi",       # ξ
    "π": r"\pi",       # π
    "ρ": r"\rho",      # ρ
    "σ": r"\sigma",    # σ
    "τ": r"\tau",      # τ
    "υ": r"\upsilon",  # υ
    "φ": r"\varphi",   # φ
    "χ": r"\chi",      # χ
    "ψ": r"\psi",      # ψ
    "ω": r"\omega",    # ω
    # Greek uppercase (only the ones distinct from Latin glyphs)
    "Γ": r"\Gamma",    # Γ
    "Δ": r"\Delta",    # Δ
    "Θ": r"\Theta",    # Θ
    "Λ": r"\Lambda",   # Λ
    "Ξ": r"\Xi",       # Ξ
    "Π": r"\Pi",       # Π
    "Σ": r"\Sigma",    # Σ
    "Φ": r"\Phi",      # Φ
    "Ψ": r"\Psi",      # Ψ
    "Ω": r"\Omega",    # Ω
}


# Matches existing math regions: $$...$$ block, then $...$ inline.
# Order matters — $$ has to be tested first or we'd partially eat it.
_MATH_REGION_RE = re.compile(r"(\$\$[\s\S]+?\$\$|\$[^$\n]+?\$)")

# A bare `\command` token outside math, including immediate subscripts /
# superscripts / single argument group:
#   \frac{a}{b}        → matches the whole thing
#   \omega_0           → matches \omega_0
#   \sum_{i=1}^{n}     → matches \sum_{i=1}^{n}
# Doesn't try to capture surrounding operators or numerals; the LLM
# polish picks those up later when wrapping the wider expression.
_BARE_COMMAND_RE = re.compile(
    r"\\[a-zA-Z]+"
    r"(?:_\{[^{}]*\}|\^\{[^{}]*\}|_[a-zA-Z0-9]|\^[a-zA-Z0-9]|\{[^{}]*\})*"
)


def _normalize_inside_math(text: str) -> str:
    """Apply the inside-math Unicode→LaTeX replacements to a span that
    is already known to be a math region."""
    for uni, latex in _UNICODE_INSIDE_MATH.items():
        if uni in text:
            text = text.replace(uni, latex)
    return text


def _spans(text: str, pattern: re.Pattern) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in pattern.finditer(text)]


def _in_any_span(pos: int, spans: list[tuple[int, int]]) -> bool:
    for start, end in spans:
        if start <= pos < end:
            return True
    return False


def normalize_latex_block(content: str) -> str:
    """Best-effort deterministic cleanup of LaTeX/math in markdown.

    Safe to call on EVERY emitted block — runs in O(n) and adds
    microseconds. Returns `content` unchanged if there's nothing to fix.
    """
    if not content:
        return content

    # ---- Pass 1a — ASCII-fy Unicode minus everywhere. ----
    # The minus sign character (U+2212) is what models love to emit but
    # KaTeX expects a plain hyphen. Replacing it in prose is harmless
    # since `-` is what English uses anyway.
    for uni, ascii_repl in _UNICODE_ALWAYS_SAFE.items():
        if uni in content:
            content = content.replace(uni, ascii_repl)

    # ---- Pass 1b — Normalize Unicode math symbols inside $...$ only. ----
    def _on_math_region(m: re.Match) -> str:
        return _normalize_inside_math(m.group(0))
    content = _MATH_REGION_RE.sub(_on_math_region, content)

    # ---- Pass 2 — Wrap bare \command tokens outside math in $...$. ----
    # Re-scan math regions because pass 1 may have introduced new spans.
    math_spans = _spans(content, _MATH_REGION_RE)

    # Walk in reverse so wrapping doesn't shift earlier positions.
    matches = list(_BARE_COMMAND_RE.finditer(content))
    for m in reversed(matches):
        if _in_any_span(m.start(), math_spans):
            continue
        token = m.group(0)
        # Defensive: skip if the token is followed immediately by `}` —
        # that means we're inside a brace group of another expression
        # (e.g. half-extracted from a multi-line span) and wrapping
        # would corrupt the structure.
        end_char = content[m.end() : m.end() + 1]
        if end_char == "}":
            continue
        content = content[: m.start()] + "$" + token + "$" + content[m.end() :]

    return content
