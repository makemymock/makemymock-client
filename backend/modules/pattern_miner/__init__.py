"""Pattern miner — read-only views over the mined reasoning-pattern catalog.

The mining itself (classifying every JEE PYQ into a reasoning pattern) runs
offline in the standalone Pattern_Miner pipeline, which writes `patterns` and
`pattern_assignments` to the PYQ cluster. This backend module is a *static*
feature: it only reads that catalog back and serves it over HTTP. No mining,
no LLM calls, no writes happen here.
"""
