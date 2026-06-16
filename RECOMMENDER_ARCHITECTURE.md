# JEE Question Recommender — Full Architecture

## Philosophy

Every minute a student spends studying should be on the highest-leverage question possible.
"Highest leverage" means: a question whose underlying concept is likely to appear in this year's
exam AND targets a genuine gap in that student's understanding AND is at the right difficulty to
produce learning without frustration.

No purely mathematical system can achieve this alone — it can tell you a student got a question
wrong but not *why*. No purely agentic system can either — LLMs are inconsistent and slow for
per-question decisions. The right design uses math for every fast decision and agents for every
deep-diagnosis decision.

---

## 1. Student Personalization Dimensions

Most recommenders track only `correct / wrong`. That captures almost nothing about a student.
The dimensions that actually matter:

### 1.1 Error Taxonomy (per topic)

| Error Type | What it means | How to detect |
|---|---|---|
| **Computation** | Knows the method, makes arithmetic/algebra slip | High inconsistency in same topic: gets it right sometimes, wrong other times |
| **Conceptual** | Wrong approach entirely | Consistently wrong regardless of difficulty in a topic |
| **Application** | Can solve standard form, fails novel setups | Correct on low-difficulty, wrong on high-difficulty same topic |
| **Speed** | Knows it but too slow for exam conditions | High time-per-question + correct OR wrong despite knowing |

Mathematical signal per topic:
```
inconsistency_rate[t] = std(binary_outcomes) / mean(binary_outcomes)
  → high value → computation error profile

difficulty_ceiling[t] = max(difficulty of questions where P(correct) > 0.5)
  → low ceiling → conceptual gap

time_z_score[t] = (student_avg_time[t] - population_avg_time[t]) / population_std_time[t]
  → high z-score → speed problem
```

These three numbers are fed to the **Diagnosis Agent** periodically, not per-question.

### 1.2 Question Type Sensitivity

Each student has a separate Beta state per question type:
```
type_state[student_id][type] = Beta(α_type, β_type)
types: single_correct, multi_correct, integer, matching
```

Integer-type questions have no elimination — many students who understand the concept still
fail them. A student with low `integer` mastery should get more integer-type drills, not easier
conceptual questions.

### 1.3 Session Fatigue Profile

Track per-session:
```
accuracy_block_1 = correct / total for questions 1-10
accuracy_block_2 = correct / total for questions 11-20
accuracy_block_3 = correct / total for questions 21-30

fatigue_drop = accuracy_block_1 - accuracy_block_3
```

If `fatigue_drop > 0.20` consistently across sessions → student's `fatigue_threshold` is ~15
questions. After that point, only serve easier questions or review questions.

### 1.4 Confidence Profile

Three confidence archetypes detected over time:
- **Brittle** — performance collapses after 2+ wrong answers. Needs more recovery injections.
- **Resilient** — performance stable even after wrong streaks. Can handle sustained hard drilling.
- **Overconfident** — high accuracy on easy questions, refuses harder ones. Needs forced difficulty increases.

Detection: track `accuracy_after_wrong_streak` vs `accuracy_baseline`. If ratio < 0.6 → brittle.

### 1.5 Avoidance Behavior

Students who are weak at a topic will often answer very fast (guessing) to avoid the discomfort.
Signal:
```
avoidance_score[t] = (1 - accuracy[t]) × (1 / time_z_score[t])
  → high score → student is guessing to skip this topic
```

This is flagged to the Diagnosis Agent which tells the Session Planner to force-include that topic.

### 1.6 Compressed Student Personality Document

After each session, the Diagnosis Agent maintains this document (< 400 tokens, always in agent context):

```json
{
  "learning_style": "procedural",
  "fatigue_threshold_questions": 18,
  "confidence_profile": "brittle",
  "improvement_rate": "medium",
  "strong_chapters": ["probability", "sequences-and-series"],
  "persistent_weak_chapters": ["differentiation", "circle"],
  "avoidance_topics": ["integration::integration-by-parts"],
  "question_type_strengths": {
    "single_correct": 0.68,
    "multi_correct": 0.41,
    "integer": 0.35,
    "matching": 0.52
  },
  "error_profile": {
    "differentiation": "computation",
    "integration": "conceptual",
    "circle": "application"
  },
  "notes": "Student rushes integer questions. Needs slow-down prompt. Improves fast in trig after drilling."
}
```

This is the ONLY student-level context agents receive. Everything else is tool calls.

---

## 2. Recent Year Trend + "What Will Appear This Year"

### 2.1 Base Trend Score (Exponential Decay)

```
λ = 0.35   # decay constant → ~3-year effective half-life

trend_score_raw(topic, current_year) =
    Σ_{y=2014}^{current_year-1}  count(topic, y) × exp(-λ × (current_year - y))
```

This gives more weight to 2024 questions than 2019 questions.

### 2.2 Gap Bonus (Topic Appears "Due")

If a topic did NOT appear last year but appeared regularly before, it is "overdue":
```
years_since_last = current_year - max(year where count(topic, year) > 0)
gap_bonus(topic) = min(1 + 0.25 × years_since_last, 1.75)
```

A topic absent for 3 years gets a 1.75x multiplier. Cap prevents runaway inflation.

### 2.3 Streak Score (Appeared Consecutively)

```
streak(topic) = length of longest streak of consecutive years with count > 0 ending at current_year-1
streak_score(topic) = 1 + 0.15 × min(streak, 5)
```

Topics appearing every year for 5+ years (e.g., quadratic equations, integration) get a 1.75x boost.

### 2.4 Volume Trend Direction

```
years = [2019, 2020, 2021, 2022, 2023, 2024]
counts = [count(topic, y) for y in years]
trend_slope = linear_regression_slope(years, counts)

direction_multiplier = 1 + 0.1 × sign(trend_slope) × min(|trend_slope|, 2)
```

Topics with increasing count get a small upward nudge. Topics declining get a penalty.

### 2.5 Final Appearance Probability

```
raw_score(topic) = trend_score_raw(topic) × gap_bonus(topic) × streak_score(topic) × direction_multiplier

# Normalize across all topics
max_raw = max(raw_score(t) for all topics t)
p_appears(topic) = sigmoid(3 × (raw_score(topic) / max_raw - 0.5))
```

This outputs a probability 0-1. Topics with `p_appears > 0.7` are "high priority this year."

### 2.6 Interpretation Example

For `integration::integration-by-substitution`:
- Appeared 2019-2024 every year (streak=6) → streak_score = 1.75
- Count increasing → direction_multiplier = 1.15
- Appeared last year → gap_bonus = 1.0
- Result: very high p_appears → always in focus topics

For `mathematical-induction::mathematical-induction`:
- Appeared 2019, 2021, 2023 (skip years) → gap_bonus = 1.25
- Last appeared 2023 → years_since_last = 1 → gap_bonus = 1.25
- Count declining → direction_multiplier = 0.9
- Result: moderate p_appears

The **Trend Intelligence Agent** recomputes all these weekly and stores in `topic_trend_scores` MongoDB collection.

---

## 3. Mathematical Core

### 3.1 Student State Per Topic

```python
{
  "student_id": "...",
  "topic_id": "differentiation::methods-of-differentiation",
  "chapter": "differentiation",

  # Thompson Sampling state
  "alpha": 4,   # correct_count + 1
  "beta": 7,    # wrong_count + 1

  # IRT state
  "theta": -0.3,  # ability estimate on logistic scale

  # Spaced repetition
  "next_review_date": "2026-06-01",
  "review_interval_days": 3,
  "easiness_factor": 2.1,

  # Session metadata
  "total_attempts": 10,
  "last_attempted": "2026-05-28T14:30:00Z"
}
```

### 3.2 IRT Update (1-Parameter Logistic)

```
P(correct | θ, b) = 1 / (1 + exp(-(θ - b)))

where:
  θ = student ability estimate for this topic
  b = question difficulty (stored in DB as: easy=−1, medium=0, hard=+1)

After each answer:
  θ_new = θ_old + η × (outcome - P(correct | θ_old, b))

where η = 0.3 (learning rate)
```

Target difficulty for next question: `b* = θ + 0.62` → P(correct) ≈ 0.65
This is the "zone of proximal development" — challenging but winnable.

### 3.3 Thompson Sampling (Topic Selection)

```
For each unlocked topic t:
  mastery_sample[t] ~ Beta(alpha[t], beta[t])   # sample from posterior
  priority[t] = (1 - mastery_sample[t]) × p_appears[t]

target_topic = argmax(priority)
```

Low samtery sample + high trend = highest urgency.
This naturally balances exploration (uncertain topics) vs exploitation (known weak topics)
without any hand-tuned α, β, γ weights.

### 3.4 Spaced Repetition (SM-2 Variant)

```
On correct answer:
  if first_time_correct:
    interval = 1 day
  else:
    interval = prev_interval × easiness_factor
  easiness_factor = max(1.3, EF + 0.1 - (5 - grade) × (0.08 + (5 - grade) × 0.02))
  grade: 5 = fast+correct, 4 = slow+correct, 3 = correct with effort

On wrong answer:
  interval = 1 day
  easiness_factor = max(1.3, EF - 0.2)
```

Any question with `next_review_date <= today` is "due" and gets a 30% chance of being
inserted into the current session regardless of topic priority.

### 3.5 Prerequisite Unlock Check

```python
MASTERY_THRESHOLD = 0.75

def mastery_mean(topic_id, student_state):
    a = student_state[topic_id]["alpha"]
    b = student_state[topic_id]["beta"]
    return a / (a + b)

def is_unlocked(topic_id, student_state, graph):
    prereqs = graph[topic_id]["requires"]
    return all(mastery_mean(p, student_state) >= MASTERY_THRESHOLD for p in prereqs)
```

Run this check after every answer. When a topic newly unlocks, add it to available pool immediately.

### 3.6 Handling Sparse Topics

If a topic has fewer than 5 questions:
- `exhaustion_ratio = questions_attempted_in_topic / total_questions_in_topic`
- If `exhaustion_ratio > 0.8`: mark topic as "near-exhausted"
- Fallback: pull from same chapter's adjacent topics (sibling nodes in graph)
- Increase spaced repetition intervals so seen questions come back at longer gaps
- Flag topic for "more questions needed" in admin dashboard

---

## 4. Agentic Layer

Agents run **asynchronously** and **never** in the per-question hot path.
Math handles every per-answer decision in milliseconds.
Agents update the parameters that math operates on.

### 4.1 Agent Roster

```
Session Planner Agent     → runs at session start (~3s)
Question Selector Agent   → runs per-question (~1s) — lightweight
Diagnosis Agent           → runs after session end or frustration event (~5s)
Trend Intelligence Agent  → runs weekly (~30s)
Confidence Regulator      → synchronous rule-engine, no LLM
```

### 4.2 Session Planner Agent

**When:** Student opens the app, starts a session.

**Context given:**
- Student personality document (< 400 tokens)
- Last 3 session summaries (< 300 tokens)
- Current date / days to exam (if set)

**Tools:**

```python
get_unlocked_topics(student_id: str) -> List[{
    "topic_id": str,
    "chapter": str,
    "mastery_mean": float,       # alpha/(alpha+beta)
    "mastery_uncertainty": float, # variance of Beta
    "p_appears_this_year": float
}]

get_due_reviews(student_id: str, limit: int = 5) -> List[{
    "question_id": str,
    "topic_id": str,
    "overdue_days": int
}]

get_weakest_unlocked(student_id: str, limit: int = 5) -> List[topic_id]

get_trend_top_topics(limit: int = 10) -> List[{
    "topic_id": str,
    "p_appears": float
}]
```

**Output (session plan):**
```json
{
  "focus_topics": ["differentiation::methods-of-differentiation", "circle::tangent-and-normal"],
  "session_mode": "drilling",
  "start_difficulty_offset": -0.3,
  "confidence_note": "Student is brittle today based on last session. Start with an easy win.",
  "review_injection_rate": 0.25
}
```

The session plan guides the math engine but does not override it. Math still makes the
final question decision — the plan just pre-filters the candidate topic pool.

### 4.3 Question Selector Agent

**When:** After Thompson Sampling identifies target_topic, before question is served.

**Why an agent here:** The math gives us a topic and a difficulty range. But within those
10 candidates, the best question also depends on:
- Student's error profile (computation-error student → avoid multi-step questions, give clean setups)
- Question type weakness (student weak at integer → inject integer more often)
- Year of question (prefer recent years for trend alignment)
- Novelty (prefer unseen)

**Tools:**

```python
get_candidate_questions(
    topic_id: str,
    difficulty_min: float,
    difficulty_max: float,
    exclude_seen_correct: List[str],
    limit: int = 10
) -> List[{
    "question_id": str,
    "difficulty": float,
    "year": int,
    "type": str,
    "is_novel": bool
}]

get_question_type_weights(student_id: str) -> Dict[str, float]
# returns: {"single_correct": 0.3, "integer": 0.5, "multi_correct": 0.2}
# weights reflect how much to prioritize each type for improvement
```

**Output:** `selected_question_id`

The agent is given a short prompt with student error profile + candidates list and picks one.
This call is fast because candidates list is small (10 items) and context is minimal.

### 4.4 Diagnosis Agent

**When:** After session ends OR after 3 consecutive wrong answers in a topic.

**Context given:** Student personality document only.

**Tools:**

```python
get_topic_attempt_stats(student_id: str, topic_ids: List[str]) -> Dict[str, {
    "total_attempts": int,
    "correct": int,
    "avg_time_seconds": float,
    "inconsistency_rate": float,  # computed by math engine
    "difficulty_ceiling": float,
    "time_z_score": float
}]

get_error_clusters(student_id: str, n_recent: int = 30) -> Dict[str, {
    "dominant_error_type": str,  # computation|conceptual|application|speed
    "confidence": float
}]

get_session_summary(session_id: str) -> SessionSummary

update_student_personality(student_id: str, updates: Dict) -> None

flag_prerequisite_gap(student_id: str, topic_id: str, gap_type: str) -> None
# gap_type: "conceptual_gap" | "needs_more_drill" | "avoidance_detected"
```

**Output:** Updated personality document + any prerequisite flags.

Example: Diagnosis Agent sees `inconsistency_rate[integration::integration-by-parts] = 0.8`,
`time_z_score = 2.1`. It infers "computation error + slow". It updates personality:
`error_profile.integration = "computation"` and sets `notes += "Needs slow integration drills with
step-by-step checking. Avoid novel setups until computation stabilizes."`

### 4.5 Trend Intelligence Agent

**When:** Weekly (cron job).

**Tools:**

```python
get_topic_year_matrix() -> Dict[str, Dict[int, int]]
# {"differentiation::methods-of-differentiation": {2019: 3, 2020: 2, 2021: 4, ...}}

compute_gap_patterns(current_year: int) -> Dict[str, {
    "years_since_last": int,
    "gap_bonus": float
}]

compute_streak_scores() -> Dict[str, float]

compute_direction_multipliers() -> Dict[str, float]

update_trend_store(scores: Dict[str, float]) -> None
# writes to MongoDB topic_trend_scores collection
```

**Output:** Updated `p_appears` scores for all 156 topics in MongoDB.

### 4.6 Confidence Regulator (Rule Engine — No LLM)

Runs synchronously in the hot path. No LLM. Pure logic.

```python
def get_session_mode(session_state: dict, student_personality: dict) -> dict:
    consecutive_wrong = session_state["consecutive_wrong"]
    questions_asked = session_state["questions_asked"]
    fatigue_threshold = student_personality["fatigue_threshold_questions"]
    confidence_profile = student_personality["confidence_profile"]

    # Frustration detection
    frustration_threshold = 2 if confidence_profile == "brittle" else 3
    if consecutive_wrong >= frustration_threshold:
        return {
            "mode": "recovery",
            "difficulty_offset": -1.0,  # serve easy question
            "topic_override": "pick_mastered_topic"  # from strong_chapters
        }

    # Fatigue detection
    if questions_asked > fatigue_threshold:
        return {
            "mode": "wind_down",
            "difficulty_offset": -0.5,
            "prefer_review": True
        }

    # Normal
    return {"mode": "normal", "difficulty_offset": 0.0}
```

---

## 5. Long Context Handling

### 5.1 Memory Hierarchy

```
Level 0: Raw event logs (never shown to agents)
  {question_id, correct, time_ms, timestamp, session_id}
  → stored in MongoDB, queried by tools

Level 1: Session Summary (generated after each session, ~200 tokens)
  {
    session_id, duration_minutes, questions_attempted,
    accuracy_by_chapter, avg_time_by_topic,
    frustration_events_count, topics_unlocked,
    first_half_accuracy, second_half_accuracy,
    hardest_correct_difficulty, easiest_wrong_difficulty
  }

Level 2: Weekly Profile (generated weekly, ~150 tokens)
  {
    week, total_sessions, total_questions,
    top_5_improving_topics, top_5_declining_topics,
    dominant_error_type_this_week,
    avg_session_duration, sessions_completed_vs_planned
  }

Level 3: Student Personality (updated monthly, ~350 tokens)
  → The compressed document described in Section 1.6
  → This is what agents always have in context
```

### 5.2 Rule: Agents Get Tools, Not Raw Data

| What agent needs | Wrong approach | Right approach |
|---|---|---|
| Student's weak topics | Dump all 156 topic states into context | Call `get_weakest_unlocked(student_id, limit=5)` |
| Recent wrong questions | Dump last 100 answers | Call `get_error_clusters(student_id, n_recent=30)` |
| Question candidates | Send 14k questions | Call `get_candidate_questions(topic, difficulty_range)` |
| Year-wise trends | Dump full year matrix | Trend scores are precomputed, call `get_trend_scores()` |

### 5.3 Session Agent Context Budget

```
Student personality doc:        ~350 tokens
Last 3 session summaries:       ~450 tokens  (150 each)
Tool call results:              ~200 tokens  (small, filtered)
System prompt + instructions:   ~300 tokens
                                ──────────
Total agent context:            ~1300 tokens
```

Well within any LLM's capability. Fast. Cheap. Accurate.

---

## 6. The Complete Selection Algorithm

### Phase A — Session Start

```
1. Load student_personality_doc (Level 3)
2. Load last_3_session_summaries (Level 2)
3. Confidence Regulator: assess starting state (normal / recovery)
4. Session Planner Agent:
     - Tools: get_unlocked_topics, get_due_reviews, get_trend_top_topics
     - Output: session_plan {focus_topics, session_mode, start_difficulty_offset}
5. Initialize: consecutive_wrong=0, questions_asked=0, recovery_mode=False
```

### Phase B — Per Question (Hot Loop, < 200ms)

```
1. Confidence Regulator check:
     → recovery mode?   → override: pick from strong_chapters, easy difficulty
     → fatigue mode?    → difficulty_offset -= 0.5
     → normal?          → proceed

2. Spaced repetition check:
     → any question due for review AND random() < review_injection_rate?
     → if yes: inject review question, go to step 7

3. Filter topics to unlocked only

4. Thompson Sampling over focus_topics ∩ unlocked:
     mastery_sample[t] ~ Beta(alpha[t], beta[t])
     priority[t] = (1 - mastery_sample[t]) × p_appears[t]
     target_topic = argmax(priority)

5. IRT targeting:
     θ = student_topic_state[target_topic].theta
     target_difficulty = θ + 0.62 + difficulty_offset

6. Question Selector Agent (async, ~1s):
     Tool: get_candidate_questions(target_topic, difficulty_range, exclude_seen_correct)
     Tool: get_question_type_weights(student_id)
     → returns: selected_question_id

7. Serve question to student
8. Start timer
```

### Phase C — After Answer

```
1. Record: {student_id, question_id, correct, time_ms}

2. Update Beta state:
     correct → alpha += 1
     wrong   → beta  += 1

3. Update IRT:
     P = 1 / (1 + exp(-(theta - difficulty)))
     theta_new = theta + 0.3 × (correct - P)

4. Update spaced repetition (SM-2)

5. Update session state:
     consecutive_wrong = 0 if correct else consecutive_wrong + 1
     questions_asked += 1

6. Prerequisite unlock check:
     for each locked topic whose prereqs include updated topic:
       if mastery_mean(updated_topic) >= 0.75: unlock it

7. Async triggers:
     if consecutive_wrong == 3: trigger Diagnosis Agent (frustration event)
     if session ended: trigger Diagnosis Agent (session summary)
```

### Phase D — Weekly (Cron)

```
1. Trend Intelligence Agent:
     → Recomputes p_appears for all 156 topics
     → Updates topic_trend_scores in MongoDB
     → Flags "overdue" topics for Session Planner priority boost
```

---

## 7. MongoDB Schema

```
Collections:

student_profiles
  {student_id, name, email, exam_date, created_at}

student_personality
  {student_id, ...personality_document..., updated_at}

student_topic_state           # 156 docs per student
  {student_id, topic_id, chapter, alpha, beta, theta,
   next_review_date, review_interval_days, easiness_factor,
   total_attempts, last_attempted}

student_question_history
  {student_id, question_id, correct, time_ms, timestamp, session_id}
  index: (student_id, timestamp)
  index: (student_id, question_id)  # for "seen" lookups

session_summaries
  {session_id, student_id, ...summary_fields..., created_at}

topic_trend_scores            # 156 docs, recomputed weekly
  {topic_id, chapter, p_appears, trend_score_raw, gap_bonus,
   streak_score, direction_multiplier, computed_at}

jee_mains_pyqs                # the 14k questions
  {question_id, chapter, topic, year, difficulty,
   type, question, options, correct_options, explanation}
  index: (chapter, topic, difficulty)
  index: (year)
```

---

## 8. What Makes This Different

| Naive recommender | This system |
|---|---|
| Same topic until "done" | Thompson Sampling naturally rotates topics |
| Shows hardest/easiest questions | IRT targets the exact difficulty band for learning |
| Ignores exam trends | p_appears weights every selection toward relevant topics |
| Treats all wrong answers the same | Error taxonomy separates conceptual from computation gaps |
| No concept of prerequisites | Dependency graph prevents showing advanced before foundational |
| LLM reads all history | Hierarchical memory keeps context < 1500 tokens always |
| Ignores frustration | Confidence Regulator injects recovery questions automatically |
| Static difficulty | θ updates after every answer, difficulty target shifts in real time |

---

## 9. Implementation Order

```
Phase 1 — Foundation (Week 1)
  [ ] MongoDB schema setup
  [ ] Upload jee_mains_pyqs to MongoDB (upload_to_mongo.py — done)
  [ ] Compute initial p_appears for all topics from year data
  [ ] student_topic_state initialization for new students (156 docs)

Phase 2 — Math Engine (Week 2)
  [ ] IRT update function
  [ ] Thompson Sampling topic selector
  [ ] Spaced repetition scheduler (SM-2)
  [ ] Prerequisite unlock checker using prereqs_math.json
  [ ] Confidence Regulator (rule engine)

Phase 3 — Agent Layer (Week 3)
  [ ] Tool implementations (MongoDB queries)
  [ ] Session Planner Agent
  [ ] Question Selector Agent
  [ ] Diagnosis Agent

Phase 4 — Trend Layer (Week 4)
  [ ] Trend score computation from year data
  [ ] Trend Intelligence Agent (weekly cron)
  [ ] p_appears integration into Thompson Sampling

Phase 5 — Personalization (Week 5)
  [ ] Error taxonomy computation (inconsistency_rate, difficulty_ceiling, time_z_score)
  [ ] Student personality document generation
  [ ] Diagnosis Agent full implementation with personality updates
  [ ] Adaptive diagnostic for new student onboarding (15 questions)
```

---

*This document is the single source of truth for the recommender system design.*
*Update it when architecture decisions change — do not let code diverge from this.*
