from __future__ import annotations

# MongoDB collections
TOPIC_STATE_COLLECTION       = "student_topic_state"
PERSONALITY_COLLECTION       = "student_personality"
QUESTION_HISTORY_COLLECTION  = "student_question_history"
SESSION_SUMMARIES_COLLECTION = "session_summaries"
TREND_SCORES_COLLECTION      = "topic_trend_scores"
SOLVED_QUESTIONS_COLLECTION  = "student_solved_questions"
JEE_QUESTIONS_COLLECTION     = "jee_mains_pyqs"

# IRT
IRT_LEARNING_RATE: float = 0.3
IRT_ZPD_OFFSET: float    = 0.62   # targets P(correct) ≈ 0.65
IRT_DIFFICULTY_EASY: float   = -1.0
IRT_DIFFICULTY_MEDIUM: float = 0.0
IRT_DIFFICULTY_HARD: float   = 1.0

# Thompson Sampling — uniform Beta prior for new topics
THOMPSON_INITIAL_ALPHA: int = 1
THOMPSON_INITIAL_BETA: int  = 1

# SM-2 spaced repetition
SM2_MIN_EASINESS_FACTOR: float     = 1.3
SM2_DEFAULT_EASINESS_FACTOR: float = 2.5
SM2_FIRST_INTERVAL_DAYS: int       = 1
SM2_REVIEW_INJECTION_PROB: float   = 0.30

# Prerequisite unlock — mastery mean threshold
MASTERY_THRESHOLD: float = 0.75

# Confidence Regulator
REGULATOR_BRITTLE_FRUSTRATION_THRESHOLD: int = 2
REGULATOR_NORMAL_FRUSTRATION_THRESHOLD: int  = 3
REGULATOR_RECOVERY_DIFFICULTY_OFFSET: float  = -1.0
REGULATOR_FATIGUE_DIFFICULTY_OFFSET: float   = -0.5

# Error taxonomy thresholds
ERROR_INCONSISTENCY_HIGH: float = 0.6
ERROR_CEILING_LOW: float        = -0.2
ERROR_TIME_Z_HIGH: float        = 1.5

# Session / agent context limits
MAX_FOCUS_TOPICS: int       = 5
MAX_CANDIDATE_QUESTIONS: int = 10
SESSION_HISTORY_WINDOW: int  = 3
ERROR_CLUSTER_WINDOW: int    = 30

# Sparse topic handling
SPARSE_TOPIC_THRESHOLD: int  = 5
NEAR_EXHAUSTION_RATIO: float = 0.8

# Trend score computation
TREND_DECAY_LAMBDA: float          = 0.35
TREND_START_YEAR: int              = 2014
TREND_GAP_BONUS_CAP: float         = 1.75
TREND_GAP_BONUS_PER_YEAR: float    = 0.25
TREND_STREAK_BONUS_PER_YEAR: float = 0.15
TREND_MAX_STREAK_YEARS: int        = 5
TREND_DIRECTION_MAX_SLOPE: float   = 2.0
TREND_DIRECTION_FACTOR: float      = 0.1
TREND_SIGMOID_SHARPNESS: float     = 3.0
TREND_HIGH_PRIORITY_THRESHOLD: float = 0.7

# Student personality defaults
PERSONALITY_MAX_TOKENS: int    = 400
DEFAULT_FATIGUE_THRESHOLD: int = 20
DEFAULT_CONFIDENCE_PROFILE: str = "resilient"
DEFAULT_LEARNING_STYLE: str    = "balanced"
DEFAULT_IMPROVEMENT_RATE: str  = "medium"

# Fatigue profiling
FATIGUE_DROP_THRESHOLD: float = 0.20
FATIGUE_BLOCK_SIZE: int       = 10

# Avoidance detection
AVOIDANCE_SCORE_THRESHOLD: float = 0.5

# Spaced-repetition: attempted-question exclusion window
# Both correct and incorrect attempts suppress a question from normal selection
# for this many days.  After the window expires the review/retry injection
# mechanism brings it back with appropriate priority.
ATTEMPTED_EXCLUSION_DAYS: int = 7

# Incorrect-answer retry scheduling
INCORRECT_FIRST_INTERVAL_DAYS: int = 1   # first retry comes back the next day
INCORRECT_MAX_INTERVAL_DAYS: int   = 3   # caps at 3 days until student gets it right
INCORRECT_INJECTION_PROB: float    = 0.55  # probability of injecting a retry question each turn
                                            # (higher than SM2_REVIEW_INJECTION_PROB = 0.30)

# Subjects supported by the recommender
SUBJECT_MATHEMATICS: str = "mathematics"
SUBJECT_PHYSICS:     str = "physics"
SUBJECT_CHEMISTRY:   str = "chemistry"
ALL_SUBJECTS: list[str]  = [SUBJECT_MATHEMATICS, SUBJECT_PHYSICS, SUBJECT_CHEMISTRY]
