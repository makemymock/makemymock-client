"""Cheap, deterministic pre-filter for the dedupe pass.

Dedupe is O(n^2) LLM calls — every pattern compared with every other. Most of
those pairs are obviously unrelated. This pre-filter scores each pair with cheap
LOCAL text similarity so the expensive dedupe LLM call runs ONLY on pairs that
are plausibly the same trick.

NOT embedding-based: no model, no network, fully deterministic. It uses classic
information retrieval:

  * TF-IDF cosine over each pattern's signature text. The clever part is IDF —
    in a chapter full of trig patterns, words like "sin", "angle", "cos" appear
    in almost every pattern, so IDF automatically discounts them, while
    distinctive terms ("telescoping", "triple-angle", "amplitude") dominate the
    score. No hand-tuned domain stopword list required; the chapter teaches the
    filter what's generic.
  * A character 3-gram Jaccard as a morphological backstop, so wording variants
    ("completing" vs "complete", "doubled" vs "double") still register.

The pair score is max(cosine, jaccard) — both signals can only RAISE the score,
biasing toward recall: we'd rather send a borderline pair to the LLM than miss
a real duplicate.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Iterable

from modules.pattern_miner.domain import Pattern

# Minimal English stopwords. Domain-generic words are handled by IDF, not here.
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "are", "be", "for",
    "with", "this", "that", "it", "as", "on", "by", "from", "when", "into",
    "its", "their", "they", "you", "your", "we", "if", "then", "than", "so",
    "which", "where", "what", "how", "use", "used", "using", "via", "can",
}

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if len(t) > 1 and t not in _STOP]


def _char_ngrams(text: str, n: int = 3) -> set[str]:
    s = re.sub(r"\s+", " ", text.lower()).strip()
    if len(s) < n:
        return {s} if s else set()
    return {s[i : i + n] for i in range(len(s) - n + 1)}


def _pattern_text(p: Pattern) -> str:
    return " ".join(
        [
            p.name,
            p.signature.trigger,
            p.signature.technique,
            p.signature.why_it_works,
            p.description,
        ]
    )


class PatternSimilarity:
    """Pre-computes per-pattern TF-IDF vectors + char-trigram sets for a chapter,
    then answers cheap pairwise similarity queries."""

    def __init__(self, patterns: Iterable[Pattern]) -> None:
        patterns = list(patterns)
        n = max(len(patterns), 1)

        docs: dict[str, list[str]] = {
            p.pattern_id: _tokens(_pattern_text(p)) for p in patterns
        }

        # Document frequency → IDF. No "+1" added to the log result, so a token
        # present in EVERY pattern gets idf 0 (correctly treated as noise).
        df: dict[str, int] = defaultdict(int)
        for toks in docs.values():
            for t in set(toks):
                df[t] += 1
        idf = {t: math.log((n + 1) / (df_t + 1)) for t, df_t in df.items()}

        self._vecs: dict[str, dict[str, float]] = {}
        for pid, toks in docs.items():
            tf = Counter(toks)
            vec = {t: tf[t] * idf.get(t, 0.0) for t in tf}
            norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
            self._vecs[pid] = {t: w / norm for t, w in vec.items()}

        self._ngrams: dict[str, set[str]] = {
            p.pattern_id: _char_ngrams(_pattern_text(p)) for p in patterns
        }

    def _cosine(self, a_id: str, b_id: str) -> float:
        va = self._vecs.get(a_id, {})
        vb = self._vecs.get(b_id, {})
        if len(va) > len(vb):  # iterate the smaller vector
            va, vb = vb, va
        return sum(w * vb.get(t, 0.0) for t, w in va.items())

    def _jaccard(self, a_id: str, b_id: str) -> float:
        na = self._ngrams.get(a_id, set())
        nb = self._ngrams.get(b_id, set())
        if not na and not nb:
            return 0.0
        inter = len(na & nb)
        union = len(na | nb) or 1
        return inter / union

    def score(self, a: Pattern, b: Pattern) -> float:
        """Similarity in [0, 1]. Higher = more likely the same pattern."""
        return max(
            self._cosine(a.pattern_id, b.pattern_id),
            self._jaccard(a.pattern_id, b.pattern_id),
        )
