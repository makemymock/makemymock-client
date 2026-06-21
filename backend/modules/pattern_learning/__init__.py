"""Pattern learning — the Duolingo-style pattern-path feature.

A student who clears a chapter's mock-test accuracy gate unlocks that chapter's
first reasoning pattern; finishing a pattern's questions (any submission counts)
unlocks the next pattern, and within a pattern questions unlock one at a time.

This module owns the per-student PROGRESS (a separate `pattern_learning` DB on
the PYQ cluster). It READS the mined catalog (patterns / assignments / questions)
from the same cluster's `adaptive_practice` DB, and reads mock-test accuracy from
the primary DB to drive the unlock gate. It never writes to the catalog.
"""
