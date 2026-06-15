"""Pattern miner — mines reasoning patterns out of the JEE PYQ catalog.

Each question is assigned to exactly one pattern. Patterns are discovered
incrementally: when no existing pattern fits, the pipeline proposes a new one
(under a per-chapter lock so concurrent workers don't mint duplicates).

The mining itself is an offline batch pass (see `jobs/`); the module also
exposes a small read-only API (controller/service) over the catalog it builds,
which powers the "patterns you've practised vs. never seen" product hook.
"""
