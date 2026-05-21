"""All tunable constants for the recommender.

Values mirror the production engine in
phase/Phase-backend/app/services/mock_test/mocktest_config.py.
"""

# ============ LAYER 1 — SCORING ============
# Higher score = topic needs more practice (the priority score is an AVG of these).

CORRECT_EASY = 3
CORRECT_MEDIUM = 2
CORRECT_HARD = 1

INCORRECT_EASY = 10
INCORRECT_MEDIUM = 8
INCORRECT_HARD = 5

# Used by Layer 5: below this many attempts, prefer easier questions when fetching.
MIN_ATTEMPTS_FOR_MIX = 5


# ============ LAYER 2 — TIME DECAY ============
# Days since user's most-recent attempt on the topic ⇒ multiplier on the base priority.

DECAY_THRESHOLD_RECENT = 3        # 0..3 days   : no penalty
DECAY_THRESHOLD_WEEK = 7          # 4..7 days   : slight boost
DECAY_THRESHOLD_TWO_WEEKS = 14    # 8..14 days  : moderate boost
DECAY_THRESHOLD_MONTH = 30        # 15..30 days : significant boost
# 31+ days : max boost (likely forgotten)

DECAY_RECENT = 1.0
DECAY_WEEK = 1.2
DECAY_TWO_WEEKS = 1.5
DECAY_MONTH = 2.0
DECAY_FORGOTTEN = 2.5


# ============ LAYER 5 — QUESTION RECYCLING ============
# Questions whose most-recent attempt is older than this can be reused.

RECYCLE_THRESHOLD_DAYS = 30


# ============ LAYER 4 — PROGRESSION ============
# Window over which "recent" performance is measured per topic.

PROGRESSION_WINDOW_SIZE = 15
MIN_ATTEMPTS_FOR_PROG = 5

# Promotion thresholds (accuracy floors that bump the user up a stage).
ACC_PROMOTE_EASY_TO_MIX = 0.7        # >70% easy-accuracy ⇒ Easy → Mix(E+M)
ACC_PROMOTE_MIX_TO_MED = 0.75        # >75% medium-accuracy while in Mix(E+M) ⇒ Medium only
ACC_PROMOTE_MED_TO_MIX_MH = 0.8      # >80% medium-accuracy while in Medium ⇒ Mix(M+H)
ACC_PROMOTE_MIX_MH_TO_HARD = 0.7     # >70% hard-accuracy while in Mix(M+H) ⇒ Hard only

# Demotion thresholds (accuracy ceilings that drop the user down a stage).
ACC_DEMOTE_TO_EASY = 0.5             # <50% easy-accuracy while in Mix(E+M) ⇒ Easy only
ACC_DEMOTE_TO_MIX_EM = 0.5           # <50% medium-accuracy while in Medium ⇒ Mix(E+M)
ACC_DEMOTE_TO_MED = 0.6              # <60% medium-accuracy while in Mix(M+H) ⇒ Medium only
ACC_DEMOTE_TO_MIX_MH = 0.6           # <60% hard-accuracy while in Hard ⇒ Mix(M+H)


# ============ LAYER 2 — RECENCY WEIGHTING ============
# When computing base_score for a topic, attempts are weighted by recency
# using a half-life decay. weight = 0.5 ^ (days_ago / RECENCY_HALFLIFE_DAYS).
#
# With 90-day half-life:
#     0 days ago  ⇒ 1.00× weight
#    30 days ago  ⇒ 0.79×
#    60 days ago  ⇒ 0.63×
#    90 days ago  ⇒ 0.50×
#   180 days ago  ⇒ 0.25×
#
# Old correct attempts still contribute (they're not erased), but recent
# wrong answers move the score faster than they would in a flat average.
# Set to None to disable recency weighting (revert to flat average).
RECENCY_HALFLIFE_DAYS: float | None = 90.0

# Recency weighting is applied via a small precomputed bucket table to
# avoid calling pow() per attempt in the hot loop. Bucket size controls
# the accuracy/table-size tradeoff:
#   30  ⇒ ~±10% intra-bucket weight variation, ~12 entries (4 half-lives)
#   7   ⇒ ~±3%  intra-bucket variation, ~52 entries (≈ a year)
#   1   ⇒ effectively no bucketing
# Each bucket's weight is taken at the bucket *midpoint*; attempts older
# than the table horizon (4 half-lives by default) clamp to the last
# bucket (weight ≈ 0.06 — practically noise).
RECENCY_BUCKET_DAYS: int = 30


# ============ LAYER 2 — COLD START ============
# Priority assigned to a topic when *all* selected topics have zero attempts.
DEFAULT_COLD_START_PRIORITY = 5.0


# ============ DIFFICULTY LABELS ============
DIFFICULTIES = ("easy", "medium", "hard")
