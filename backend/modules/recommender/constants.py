"""
Collection names, tuning constants, and fixed parameters for the JEE Recommender.

All numeric knobs that affect recommendation quality live here so they can be
adjusted without touching algorithmic code. Each constant is annotated with
the architecture section it originates from (RECOMMENDER_ARCHITECTURE.md).
"""

# ---------------------------------------------------------------------------
# MongoDB collections owned by this module
# ---------------------------------------------------------------------------

TOPIC_STATE_COLLECTION = "student_topic_state"
PERSONALITY_COLLECTION = "student_personality"
QUESTION_HISTORY_COLLECTION = "student_question_history"
SESSION_SUMMARIES_COLLECTION = "session_summaries"
TREND_SCORES_COLLECTION = "topic_trend_scores"

# Read-only JEE questions catalog.
# Lives in a separate MongoDB database (adaptive_practice) on the same cluster.
# Uploaded via jee_mains_pyqs_data_base/upload_to_mongo.py.
JEE_QUESTIONS_COLLECTION = "jee_mains_pyqs"

# ---------------------------------------------------------------------------
# IRT — §3.2
# ---------------------------------------------------------------------------

# Learning rate η for the 1-PL IRT update rule.
IRT_LEARNING_RATE: float = 0.3

# Zone-of-proximal-development offset added to θ to compute target difficulty.
# b* = θ + ZPD_OFFSET  →  P(correct) ≈ 0.65  (challenging but winnable).
IRT_ZPD_OFFSET: float = 0.62

# Difficulty scale: easy = -1, medium = 0, hard = +1 (stored in DB).
IRT_DIFFICULTY_EASY: float = -1.0
IRT_DIFFICULTY_MEDIUM: float = 0.0
IRT_DIFFICULTY_HARD: float = 1.0

# ---------------------------------------------------------------------------
# Thompson Sampling — §3.3
# ---------------------------------------------------------------------------

# Initial alpha/beta for a brand-new topic state (uniform Beta prior).
THOMPSON_INITIAL_ALPHA: int = 1
THOMPSON_INITIAL_BETA: int = 1

# ---------------------------------------------------------------------------
# Spaced Repetition (SM-2 variant) — §3.4
# ---------------------------------------------------------------------------

# Minimum easiness factor; prevents intervals from collapsing to zero.
SM2_MIN_EASINESS_FACTOR: float = 1.3

# Default starting EF for a new topic.
SM2_DEFAULT_EASINESS_FACTOR: float = 2.5

# First correct → 1 day; subsequent intervals scale by EF.
SM2_FIRST_INTERVAL_DAYS: int = 1

# Probability that a due review question is injected into the current slot.
SM2_REVIEW_INJECTION_PROB: float = 0.30

# ---------------------------------------------------------------------------
# Prerequisite unlock — §3.5
# ---------------------------------------------------------------------------

# Mastery mean (α/(α+β)) threshold a topic must reach for its children to unlock.
MASTERY_THRESHOLD: float = 0.75

# ---------------------------------------------------------------------------
# Confidence Regulator — §4.6
# ---------------------------------------------------------------------------

# Consecutive wrong answers before the regulator fires for each profile.
REGULATOR_BRITTLE_FRUSTRATION_THRESHOLD: int = 2
REGULATOR_NORMAL_FRUSTRATION_THRESHOLD: int = 3

# Difficulty offsets applied by the regulator.
REGULATOR_RECOVERY_DIFFICULTY_OFFSET: float = -1.0
REGULATOR_FATIGUE_DIFFICULTY_OFFSET: float = -0.5

# ---------------------------------------------------------------------------
# Error Taxonomy — §1.1
# ---------------------------------------------------------------------------

# Inconsistency rate cutoff: above this → computation-error profile.
ERROR_INCONSISTENCY_HIGH: float = 0.6

# Difficulty ceiling cutoff: below this → conceptual-gap profile.
ERROR_CEILING_LOW: float = -0.2

# Time z-score cutoff: above this → speed problem.
ERROR_TIME_Z_HIGH: float = 1.5

# ---------------------------------------------------------------------------
# Session / agent context limits — §5.3
# ---------------------------------------------------------------------------

# Maximum topics included in the Session Planner's focus list.
MAX_FOCUS_TOPICS: int = 5

# Maximum questions fetched per Question Selector call.
MAX_CANDIDATE_QUESTIONS: int = 10

# Number of recent session summaries sent to the Session Planner.
SESSION_HISTORY_WINDOW: int = 3

# Number of recent answers used for error-cluster computation.
ERROR_CLUSTER_WINDOW: int = 30

# ---------------------------------------------------------------------------
# Sparse topic handling — §3.6
# ---------------------------------------------------------------------------

# Topics with fewer questions than this are considered sparse.
SPARSE_TOPIC_THRESHOLD: int = 5

# Ratio of attempted/total above which a topic is "near exhausted".
NEAR_EXHAUSTION_RATIO: float = 0.8

# ---------------------------------------------------------------------------
# Trend score computation — §2
# ---------------------------------------------------------------------------

# Exponential decay constant (λ = 0.35 → ~2-year effective half-life).
TREND_DECAY_LAMBDA: float = 0.35

# Earliest year of JEE Mains data in the question catalog.
TREND_START_YEAR: int = 2014

# Gap bonus: max multiplier for an overdue topic (capped at 1.75×).
TREND_GAP_BONUS_CAP: float = 1.75

# Gap bonus per year of absence.
TREND_GAP_BONUS_PER_YEAR: float = 0.25

# Streak bonus per consecutive year (max 5 years → 1.75×).
TREND_STREAK_BONUS_PER_YEAR: float = 0.15
TREND_MAX_STREAK_YEARS: int = 5

# Direction multiplier: max slope magnitude that receives a nudge.
TREND_DIRECTION_MAX_SLOPE: float = 2.0
TREND_DIRECTION_FACTOR: float = 0.1

# Sigmoid sharpness for final p_appears normalization.
TREND_SIGMOID_SHARPNESS: float = 3.0

# Topics with p_appears above this are labelled "high priority this year".
TREND_HIGH_PRIORITY_THRESHOLD: float = 0.7

# ---------------------------------------------------------------------------
# Student personality document
# ---------------------------------------------------------------------------

# Absolute token budget for the compressed personality document sent to agents.
PERSONALITY_MAX_TOKENS: int = 400

# Default values for a freshly initialized student.
DEFAULT_FATIGUE_THRESHOLD: int = 20
DEFAULT_CONFIDENCE_PROFILE: str = "resilient"
DEFAULT_LEARNING_STYLE: str = "balanced"
DEFAULT_IMPROVEMENT_RATE: str = "medium"

# ---------------------------------------------------------------------------
# Fatigue profiling — §1.3
# ---------------------------------------------------------------------------

# Accuracy drop between block-1 and block-3 that signals fatigue.
FATIGUE_DROP_THRESHOLD: float = 0.20
FATIGUE_BLOCK_SIZE: int = 10

# ---------------------------------------------------------------------------
# Avoidance detection — §1.5
# ---------------------------------------------------------------------------

# avoidance_score = (1 - accuracy) × (1 / time_z) above this triggers a flag.
AVOIDANCE_SCORE_THRESHOLD: float = 0.5
