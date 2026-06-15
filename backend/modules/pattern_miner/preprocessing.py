"""Turn a raw `jee_mains_pyqs` doc into the clean text shape the agents see.

Three concerns live here:
  * `should_skip`  — questions we exclude from v1 mining (image-only, bonus, …)
  * `html_to_text` — strip HTML markup, keep the math delimiters intact
  * `normalize_raw_question` — assemble a CleanedQuestion from the raw doc
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from modules.pattern_miner.domain import CleanedQuestion

_WS_RE = re.compile(r"[ \t]+")
_BLANK_LINE_RE = re.compile(r"\n{3,}")


def should_skip(raw_doc: dict) -> tuple[bool, str]:
    """Returns (should_skip, reason). The pipeline logs the reason so we can
    audit coverage later."""
    if raw_doc.get("isImgQuestion"):
        return True, "image-only question"
    if raw_doc.get("isOutOfSyllabus"):
        return True, "out of syllabus"
    if raw_doc.get("isBonus"):
        return True, "bonus question"
    if not (raw_doc.get("question") or "").strip():
        return True, "empty question text"
    return False, ""


def html_to_text(html: str) -> str:
    """Strip HTML, drop <img> entirely, keep math delimiters intact.

    The raw `question`, `options[*].content`, and `explanation` fields are HTML
    fragments (sometimes with embedded LaTeX in `\\( … \\)` or `$ … $`). The
    agent prompts work much better on plain text — and stripping markup cuts
    token cost by ~30%.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    # Drop images outright — we filter image-only questions upstream.
    for img in soup.find_all("img"):
        img.decompose()
    text = soup.get_text(separator=" ", strip=False)
    text = _WS_RE.sub(" ", text)
    text = _BLANK_LINE_RE.sub("\n\n", text)
    return text.strip()


def _format_options(options: list[dict]) -> str:
    if not options:
        return ""
    parts: list[str] = []
    for opt in options:
        ident = (opt.get("identifier") or "").strip()
        content = html_to_text(opt.get("content") or "")
        if ident and content:
            parts.append(f"({ident}) {content}")
        elif content:
            parts.append(content)
    return "\n".join(parts)


def _resolve_answer(raw: dict) -> str:
    """Return a human-readable answer string.

    Prefer, in order:
      1. explicit `answer` if it exists (numeric / direct value).
      2. correct option's content joined.
      3. fallback to `correct_options` as a comma-separated identifier list.
    """
    explicit = raw.get("answer")
    if explicit not in (None, ""):
        return str(explicit)

    correct_ids = raw.get("correct_options") or []
    if not correct_ids:
        return ""

    options = raw.get("options") or []
    by_ident = {(o.get("identifier") or "").strip(): o for o in options}
    picked = []
    for cid in correct_ids:
        opt = by_ident.get(str(cid).strip())
        if opt:
            content = html_to_text(opt.get("content") or "")
            if content:
                picked.append(f"({cid}) {content}")
    if picked:
        return " ; ".join(picked)
    return ", ".join(str(c) for c in correct_ids)


def normalize_raw_question(raw: dict) -> CleanedQuestion:
    """Convert a raw Mongo doc → CleanedQuestion. Assumes `should_skip` has
    already cleared this doc."""
    return CleanedQuestion(
        question_id=str(raw.get("question_id", "")),
        subject=str(raw.get("subject", "")),
        chapter=str(raw.get("chapter", "")),
        topic=str(raw.get("topic", "")),
        year=int(raw.get("year") or 0),
        difficulty=str(raw.get("difficulty", "")),
        question_text=html_to_text(raw.get("question") or ""),
        options_text=_format_options(raw.get("options") or []),
        answer_text=_resolve_answer(raw),
        explanation_text=html_to_text(raw.get("explanation") or ""),
    )
