"""Collection names, prompt versioning, confidence thresholds, tuning knobs.

All four collections live on the main backend database (the same Motor client
every other module uses). `jee_mains_pyqs` is read-only here — it's populated
out-of-band by the `jee_mains_pyqs_data_base` uploader; the miner only ever
writes to `patterns`, `pattern_assignments`, and its checkpoint collection.
"""

# ---- Mongo collections ----
PYQ_COLLECTION = "jee_mains_pyqs"             # source catalog (read-only)
PATTERNS_COLLECTION = "patterns"
ASSIGNMENTS_COLLECTION = "pattern_assignments"
CHECKPOINT_COLLECTION = "pattern_miner_checkpoints"

# ---- Prompt version ----
# Bump whenever any agent prompt changes. Lets reruns overwrite stale
# assignments only when the reasoning logic actually changed.
PROMPT_VERSION = "v1"

# ---- Confidence thresholds ----
# Deliberately permissive: the bigger risk is an over-granular catalog (a new
# near-duplicate pattern per question), so we lean toward joining an existing
# pattern. Equal floors avoid the old inversion where a lone match was accepted
# at 0.55 but a contested one needed 0.65 — i.e. adding a rival made acceptance
# HARDER. Raise these if you start seeing wrong-bucket assignments.
STAGE1_MIN_CONFIDENCE = 0.50
STAGE2_MIN_CONFIDENCE = 0.50

# Two patterns are merged only when the dedupe agent is at least this confident
# they are the same trick. Higher than the match floors on purpose: a wrong
# merge is destructive (deletes a pattern + re-points assignments), so the bar
# to merge is stricter than the bar to join.
DEDUPE_MIN_CONFIDENCE = 0.70

# Pre-filter gate for the dedupe O(n^2) pass: only pairs whose cheap local text
# similarity (TF-IDF cosine / char-trigram Jaccard, see prefilter.py) is at
# least this score are sent to the dedupe LLM. Lower = more pairs checked
# (higher recall, less savings); higher = fewer LLM calls but risk missing a
# real duplicate. Set to 0.0 to disable the pre-filter (compare all pairs).
DEDUPE_PREFILTER_MIN_SIM = 0.20

# ---- Tuning ----
# How many async workers process questions concurrently in the batch pass, and
# how many patterns get serialised into a single stage-1 prompt.
WORKER_COUNT = 4
CHUNK_SIZE = 20

# Per-agent sampling temperatures. The reducers run cold (we want consistent
# verdicts); the namer runs a little warmer so descriptions don't read like
# boilerplate.
STAGE1_TEMPERATURE = 0.1
STAGE2_TEMPERATURE = 0.05
NAMER_TEMPERATURE = 0.4
DEDUPE_TEMPERATURE = 0.1
