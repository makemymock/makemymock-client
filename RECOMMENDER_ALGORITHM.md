# JEE Adaptive Recommender — Complete Algorithm

> **Scope:** This document describes every mathematical model, agentic decision, and data-flow rule that drives the MakeMyMock adaptive practice engine. It is the single authoritative reference for tuning, debugging, and extending the system.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Data Model](#2-data-model)
3. [Mathematical Engine](#3-mathematical-engine)
   - 3.1 Item Response Theory (IRT)
   - 3.2 Thompson Sampling — Topic Selection
   - 3.3 SM-2 Spaced Repetition (Correct Answers)
   - 3.4 Incorrect-Answer Retry Scheduling
   - 3.5 Attempted-Question Exclusion Window
   - 3.6 Prerequisite Graph & Unlock Logic
   - 3.7 Confidence Regulator
   - 3.8 Error Taxonomy
4. [Trend Intelligence Engine](#4-trend-intelligence-engine)
5. [Agentic Layer](#5-agentic-layer)
   - 5.1 SessionPlannerAgent
   - 5.2 QuestionSelectorAgent
   - 5.3 DiagnosisAgent
   - 5.4 LatexConverterAgent
   - 5.5 TrendIntelligenceAgent
6. [Session Lifecycle](#6-session-lifecycle)
7. [Per-Turn Question Selection Pipeline](#7-per-turn-question-selection-pipeline)
8. [Tuning Constants Reference](#8-tuning-constants-reference)

---

## 1. Architecture Overview

The recommender is a **hybrid system**: a purely-mathematical scoring layer runs at every question turn (fast, deterministic), while LLM agents layer on top for session-level planning and post-session diagnosis (slower, adaptive).

```
┌─────────────────────────────────────────────────────────────────┐
│                        Per-Session                              │
│  ┌──────────────────┐    SSE events    ┌──────────────────────┐ │
│  │ SessionPlanner   │  ────────────►   │  Frontend Think Panel│ │
│  │ Agent (Gemini)   │                  │  (live step stream)  │ │
│  └──────────────────┘                  └──────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Per-Question Turn                          │
│                                                                 │
│  Incorrect Retry Queue ──► inject? (p=0.55)                    │
│  SM-2 Review Queue     ──► inject? (p=0.30)                    │
│  ThompsonSampler       ──► pick topic from unlocked set         │
│  IRTEngine             ──► compute difficulty band              │
│  QuestionSelectorAgent ──► pick best candidate (Gemini fast)    │
│  LatexConverterAgent   ──► render KaTeX (Gemini flash)          │
└─────────────────────────────────────────────────────────────────┘
                              ▼ (on answer)
┌─────────────────────────────────────────────────────────────────┐
│                      Answer Processing                          │
│                                                                 │
│  IRT theta update · BKT alpha/beta update · SM-2 schedule       │
│  Prerequisite unlock check · Confidence regulator update        │
│  DiagnosisAgent (async, triggered on frustration or session end)│
└─────────────────────────────────────────────────────────────────┘
```

**Two MongoDB clusters:**
- **Main DB** (`makemymock`) — auth, mock tests, battles. No recommender data.
- **PYQ DB** (`adaptive_practice`) — JEE questions catalog (`jee_mains_pyqs`) + all recommender student state (`student_topic_state`, `student_solved_questions`, `student_personality`, `student_question_history`, `session_summaries`, `topic_trend_scores`).

---

## 2. Data Model

### 2.1 Per-Topic State — `student_topic_state`

One document per `(student_id, topic_id)`. Topic ID format: `"chapter::topic"` (e.g., `"limits::continuity-and-differentiability"`).

| Field | Type | Description |
|-------|------|-------------|
| `alpha` | int | BKT success count, starts at 1 |
| `beta` | int | BKT failure count, starts at 1 |
| `theta` | float | IRT ability estimate, starts at 0.0 |
| `review_interval_days` | int | SM-2 interval (days until next review), starts at 1 |
| `easiness_factor` | float | SM-2 EF, starts at 2.5 |
| `next_review_date` | str | ISO-8601 date for next topic-level review |
| `total_attempts` | int | Cumulative questions answered in this topic |
| `total_correct` | int | Cumulative correct answers |
| `last_attempted` | datetime | Timestamp of last answer |
| `subject` | str | `"mathematics"` / `"physics"` / `"chemistry"` |
| `chapter` | str | Chapter name (denormalised from topic_id) |

**Mastery mean** (BKT posterior):
```
mastery_mean = α / (α + β)
```
Starts at 0.5 (uninformed prior). Approaches 1.0 as the student answers more questions correctly.

**Mastery uncertainty** (BKT posterior variance):
```
mastery_uncertainty = (α·β) / ((α+β)² · (α+β+1))
```
Used by Thompson Sampling to explore uncertain topics.

---

### 2.2 Per-Question State — `student_solved_questions`

One document per `(student_id, question_id)`. Tracks every question the student has ever seen.

| Field | Type | Description |
|-------|------|-------------|
| `last_correct` | bool | Whether the most recent attempt was correct |
| `times_attempted` | int | Total attempts on this exact question |
| `times_correct` | int | Times answered correctly |
| `consecutive_incorrect` | int | Consecutive wrong streak (resets on correct) |
| `review_interval_days` | int | Days until next review (SM-2 for correct; 1–3 for wrong) |
| `next_review_date` | str | ISO date when question re-enters the candidate pool |
| `easiness_factor` | float | SM-2 EF (only meaningful if `last_correct=True`) |
| `subject` | str | Subject of the question |

---

### 2.3 Student Personality — `student_personality`

One document per student. Maintained entirely by the **DiagnosisAgent**.

| Field | Type | Description |
|-------|------|-------------|
| `learning_style` | str | `visual` / `pattern` / `conceptual` / `practice` / `balanced` |
| `fatigue_threshold_questions` | int | Questions before wind-down mode kicks in |
| `confidence_profile` | str | `resilient` (default) or `brittle` |
| `improvement_rate` | str | `fast` / `medium` / `slow` |
| `strong_chapters` | list | Chapters where mastery is consistently high |
| `persistent_weak_chapters` | list | Chapters with chronic low mastery |
| `avoidance_topics` | list | Topics flagged for avoidance behaviour |
| `question_type_strengths` | dict | Per-type accuracy: `{single_correct: 0.7, integer: 0.4, …}` |
| `error_profile` | dict | Per-topic dominant error type (`computation`/`conceptual`/`application`/`speed`) |
| `notes` | str | DiagnosisAgent free-text summary (≤400 tokens) |

---

## 3. Mathematical Engine

### 3.1 Item Response Theory (IRT)

**Model:** 1-Parameter Logistic (1-PL Rasch model).

The probability that a student with ability **θ** (theta) answers a question with difficulty **d** correctly:

```
P(correct | θ, d) = σ(θ − d) = 1 / (1 + exp(−(θ − d)))
```

- `θ = 0.0` → medium ability (initial state for all students)
- `d = −1.0` → easy, `d = 0.0` → medium, `d = 1.0` → hard

**Theta update** (online gradient descent on log-likelihood):

```
θ_new = θ + η · (y − P(correct | θ, d))
```

where:
- `η = 0.3` (learning rate)
- `y = 1` if correct, `y = 0` if incorrect

If correct: θ increases (student appears stronger).
If incorrect: θ decreases (student appears weaker).

**Zone of Proximal Development (ZPD) targeting:**

To target ~65% success rate (challenging but not frustrating):

```
d_target = θ + 0.62
```

The `+0.62` offset shifts the difficulty above θ such that `P(correct) ≈ σ(−0.62) ≈ 0.65`.

**Difficulty band** (±0.4 around target):

```
[d_min, d_max] = [d_target − 0.4, d_target + 0.4]
```

This band is passed to the question catalog query so candidates are within `[d_min, d_max]`.

---

### 3.2 Thompson Sampling — Topic Selection

Topics are modelled with **Beta(α, β)** distributions (BKT-inspired Bayesian Knowledge Tracing). At each turn, the engine samples from every unlocked topic's distribution and selects the weakest one relative to its exam importance.

**Priority score for topic `t`:**

```
priority(t) = (1 − sample_t) × trend_score(t)
```

where:
- `sample_t ~ Beta(α_t, β_t)` — stochastic mastery sample
- `trend_score(t) = p_appears(t)` — probability topic appears in JEE this year (see §4)

**Why Thompson Sampling?**
It naturally balances exploration (high uncertainty → high spread → sometimes samples low even if mean is high) and exploitation (genuinely weak topics reliably rank high). No explicit exploration bonus parameter is needed.

**Focus filtering:** If the student selected specific chapters, `topic_states` is filtered to `focus_topics ∩ unlocked_set` before sampling. Falls back to all unlocked topics if the filtered set is empty.

---

### 3.3 SM-2 Spaced Repetition (Correct Answers)

Based on SuperMemo SM-2 algorithm. Applies at the **topic level** (next topic-level review) and the **per-question level** (when to resurface an exact question).

**Grade computation:**

```
grade = 5   if correct AND time_ms ≤ avg_time_ms
grade = 4   if correct AND time_ms > avg_time_ms
grade = 0   if incorrect
```

(`avg_time_ms = 60 000` ms, i.e., 1 minute, as a fixed population estimate.)

**Easiness Factor update:**

```
EF_delta = 0.1 − (5 − grade) · (0.08 + (5 − grade) · 0.02)
EF_new   = max(1.3, EF + EF_delta)
```

| Grade | EF_delta |
|-------|----------|
| 5 | +0.10 |
| 4 | +0.00 |
| 3 | −0.14 |
| 0 | −0.30 |

Minimum EF is `1.3`. Default EF is `2.5`.

**Interval update (correct):**

```
first correct:  interval = 1 day
subsequent:     interval = round(interval × EF)
```

**Interval update (incorrect):**

```
EF_new   = max(1.3, EF − 0.2)
interval = 1  (topic review resets)
```

**Next review date:**

```
next_review_date = today + interval days
```

---

### 3.4 Incorrect-Answer Retry Scheduling

Incorrect answers have a separate, shorter retry schedule so the student revisits their mistakes quickly.

**Per-question retry interval:**

```
first attempt wrong:   interval = 1 day
repeated wrong:        interval = min(3, max(1, current_interval))
gets it right:         transitions to SM-2 (long interval)
consecutive_incorrect  counter reset to 0 on correct
```

This caps retry intervals at **3 days** regardless of how many times the student gets it wrong.

**Injection priority:** At each question turn, before any other selection logic:

```
P(inject incorrect retry) = 0.55
P(inject SM-2 review)     = 0.30
```

Incorrect retries are checked first (higher probability). The student will see their recent mistakes roughly every other question when they are due.

**Retry ordering:** Due-incorrect queue is sorted by `consecutive_incorrect DESC, next_review_date ASC` — the student with the most repeated failures sees those first.

---

### 3.5 Attempted-Question Exclusion Window

Every question a student has attempted (correct or incorrect) is excluded from the **normal candidate pool** for **7 days** after their last attempt.

```
excluded = { q_id | next_review_date(q_id) > today }
```

Questions only re-enter the pool through the **injection mechanism** (§3.3 / §3.4), not through random selection. This prevents the same question appearing again too soon while still guaranteeing it returns at the scheduled review.

---

### 3.6 Prerequisite Graph & Unlock Logic

**Mathematics only.** The graph is loaded from `prereqs_math.json`. Each node is:

```json
{
  "chapter::topic": {
    "chapter": "...",
    "requires": ["chapter::prereq_topic_1", ...]
  }
}
```

**Unlock condition for topic `t`:**

```
is_unlocked(t) = ∀ prereq ∈ requires(t) :  mastery_mean(prereq) ≥ 0.75
```

- If a topic has no prerequisites → always unlocked.
- If a topic is **not in the graph** (all Physics/Chemistry topics) → always unlocked.

**Threshold:** `MASTERY_THRESHOLD = 0.75`  
This is the BKT posterior mean α/(α+β) ≥ 0.75, meaning the student has demonstrated ~75% competency in the prerequisite.

**Newly-unlocked detection** (after each answer):

```
newly_unlocked = {
  dep | dep in dependents(updated_topic)
       AND is_unlocked(dep, current_states)
}
```

Returned in `SubmitAnswerResponse.newly_unlocked_topics` and shown as a celebration in the UI.

---

### 3.7 Confidence Regulator

Monitors in-session performance and switches **session mode** when the student is struggling or fatigued.

**Frustration threshold:**

| `confidence_profile` | Recovery trigger |
|---------------------|-----------------|
| `brittle` | ≥ 2 consecutive wrong |
| `resilient` (default) | ≥ 3 consecutive wrong |

**Session modes:**

| Mode | Trigger | Difficulty offset | Topic selection |
|------|---------|-------------------|-----------------|
| `normal` | — | 0.0 | Focus topics |
| `recovery` | Consecutive wrong ≥ threshold | −1.0 | Pick from strong chapters |
| `wind_down` | `questions_asked > fatigue_threshold` | −0.5 | Prefer reviews |

In `recovery` mode, `difficulty_offset = −1.0` shifts d_target well below θ, giving the student easy questions to rebuild confidence. Topic override ensures only mastered chapters are used.

The session mode is a **hot-state** variable — it recomputes at every call to `get_next_question` so it adapts within a session.

---

### 3.8 Error Taxonomy

The `ErrorTaxonomyComputer` classifies student errors into four types using three signals from recent attempts:

**1. Inconsistency Rate** (flip-flopping between correct/incorrect on same topic):

```
inconsistency_rate = std(outcomes) / mean(outcomes)    [if mean ≠ 0 or 1]
```

**2. Difficulty Ceiling** (highest difficulty the student solves correctly more than 50% of the time):

```
ceiling = max{ d | accuracy(d) > 0.5 }
```

**3. Time Z-Score** (is the student unusually slow?):

```
time_z = (student_avg_ms − pop_mean_ms) / pop_std_ms
```

**Classification rules (priority order):**

| Condition | Error type |
|-----------|-----------|
| `ceiling < −0.2` | **Conceptual** — can't solve even easy questions correctly |
| `inconsistency_rate > 0.6` | **Computation** — knows concept but makes careless errors |
| `0 ≤ ceiling ≤ 0.3` | **Application** — understands basics but struggles with medium difficulty |
| `time_z > 1.5` | **Speed** — correct but too slow |
| else | None |

**Avoidance detection:**

```
avoidance_score = (1 − accuracy) / max(time_z, 0.1)
```

High score = student answers quickly (low time_z denominator) but incorrectly. Flagged by DiagnosisAgent via `flag_prerequisite_gap`.

---

## 4. Trend Intelligence Engine

The `TrendScoreComputer` estimates the probability a topic will appear in this year's JEE exam, using historical question data from 2014 onwards.

### 4.1 Raw Trend Score

Exponential decay weights recent appearances more heavily:

```
trend_score_raw = Σ_{y=2014}^{current-1} count(topic, y) · exp(−λ · (current_year − y))
```

`λ = 0.35` — half-life of ~2 years. A topic that appeared 5 years ago contributes only `e^(−1.75) ≈ 17%` as much as a topic that appeared last year.

### 4.2 Gap Bonus

A topic that hasn't appeared recently is "overdue" — JEE often cycles through topics:

```
years_since_last = (current_year − 1) − last_appeared_year
gap_bonus        = min(1.75, 1.0 + 0.25 · years_since_last)
```

A topic absent for 3 years gets `gap_bonus = min(1.75, 1.75) = 1.75`.

### 4.3 Streak Score

Topics appearing consistently every year deserve extra weight:

```
streak        = number of consecutive recent years with appearances
streak_score  = 1.0 + 0.15 · min(streak, 5)
```

Maximum boost from streak: `1.75` (5 consecutive years).

### 4.4 Direction Multiplier

Detects whether a topic's appearances are trending up or down over the last 6 years:

```
slope          = linear_regression_slope(counts over last 6 years)
clamped_slope  = clip(slope, −2.0, 2.0)
direction_mult = 1.0 + 0.1 · sign(slope) · |clamped_slope|
```

An upward trend (slope > 0) adds up to +20% weight. A downward trend removes up to −20%.

### 4.5 Combined Score

```
raw_combined = trend_score_raw × gap_bonus × streak_score × direction_mult
```

### 4.6 Normalisation to p_appears

Scores are normalised across all topics using a **sigmoid** so the output is a probability in (0, 1):

```
p_appears(t) = σ(k · (raw_combined(t) / max_raw − 0.5))
```

where `k = 3.0` (sharpness). A topic at the 50th percentile of the score distribution gets `p_appears = 0.5`. The best-scoring topic approaches `p_appears → 1.0`.

**High-priority threshold:** `p_appears ≥ 0.70`

---

## 5. Agentic Layer

All agents use **Google Vertex AI Gemini** via Application Default Credentials (ADC). No API keys stored — uses `gcloud auth application-default login` on dev, Cloud Run identity in production.

### 5.1 SessionPlannerAgent

**Model:** `gemini-2.5-flash` (heavy; supports multi-step reasoning)  
**Triggered:** Once at session start (via SSE stream to frontend)  
**Max tool rounds:** 5

**Tools available:**

| Tool | Returns |
|------|---------|
| `get_unlocked_topics` | All unlocked topics with mastery stats and p_appears |
| `get_due_reviews` | Topics/questions due for SM-2 review today |
| `get_weakest_unlocked` | Top-5 topics by lowest mastery_mean |
| `get_trend_top_topics` | Top-10 topics by p_appears |

**System prompt directives:**

1. **Focus topics** (3–5): blend weakest unlocked with ≥1 high-trend topic (`p_appears > 0.6`)
2. **Session mode**: `recovery` if brittle + frustration; `drilling` if accuracy trending up; `review` if many due topics; else `mixed`
3. **start_difficulty_offset**: negative for low-confidence students, positive for streak
4. **review_injection_rate**: 0.1–0.4
5. **confidence_note**: direct "you" address naming strongest and weakest topic

**Output JSON** (parsed deterministically after tool loop):

```json
{
  "focus_topics":            ["chapter::topic", ...],
  "session_mode":            "mixed",
  "start_difficulty_offset": 0.0,
  "review_injection_rate":   0.25,
  "confidence_note":         "You've been doing well in Kinematics..."
}
```

**Fallback:** If Gemini fails, returns hardcoded `{mode: mixed, offset: 0.0, rate: 0.25, topics: []}`.

**SSE streaming:** Each tool call fires `{type: "step", tool, label, index}` to the frontend in real time. After the plan is parsed, `{type: "confidence", text}` is fired, then `{type: "plan", ...}`.

---

### 5.2 QuestionSelectorAgent

**Model:** `gemini-2.0-flash-lite` (fast, cheap; no tool use)  
**Triggered:** Every question turn, after topic selection

**Input to LLM:**

```json
{
  "error_profile": {"limits::continuity": "conceptual", ...},
  "type_improvement_weights": {"integer": 0.8, "single_correct": 0.3, ...},
  "candidates": [
    {"question_id": "...", "type": "integer", "difficulty": 0.7, "year": 2023, "is_novel": true},
    ...
  ]
}
```

**Scoring priority (system prompt instructs model):**

1. Highest `type_weight` → student needs most practice in that type
2. `is_novel = true` → prefer unseen questions
3. Most recent `year` → newer JEE questions are more relevant
4. Closest difficulty to IRT target

**Deterministic fallback** (if LLM fails or returns invalid ID):

```python
score(candidate) = type_weight(type)
                 + 0.20 · is_novel
                 + (year − 2019) · 0.02
```

The candidate with the highest score is selected.

**Expected output:** `{"selected_question_id": "<id>"}`

---

### 5.3 DiagnosisAgent

**Model:** `gemini-2.5-flash` (heavy; tool use, up to 8 rounds)  
**Triggered async** (never blocks the student):
- **Frustration trigger:** `consecutive_wrong ≥ 3`
- **Session-end trigger:** every `POST /session/end`

**Tools available:**

| Tool | Purpose |
|------|---------|
| `get_error_clusters` | Last 30 answers → dominant error type per topic |
| `get_topic_attempt_stats` | Inconsistency rate, difficulty ceiling, time z-score for specific topics |
| `get_session_summary` | Full session data by session_id |
| `update_student_personality` | Write new fields to personality document |
| `flag_prerequisite_gap` | Add topic to avoidance_topics / weak lists |

**Workflow (system prompt enforces order):**
1. `get_error_clusters` → identify dominant error type per topic
2. `get_topic_attempt_stats` for 3–5 lowest-mastery topics
3. `get_session_summary` if frustration trigger
4. `update_student_personality` with evidence-based fields only
5. `flag_prerequisite_gap` if avoidance detected
6. Final `update_student_personality` with 2–3 sentence `notes` summary

**Output:** `{"diagnosis_complete": true, "main_finding": "..."}`  
The actual changes are in the personality document (side-effected via tools).

---

### 5.4 LatexConverterAgent

**Model:** `gemini-3.5-flash` (fast; single turn, JSON output)  
**Triggered:** On every `GET /recommender/question/{id}` for non-image questions

**Conversion rules enforced by system prompt:**

| Rule | Example |
|------|---------|
| Inline math → `$...$` | `x²` → `$x^2$` |
| Display math → `$$...$$` | Standalone equations |
| Fractions → `\frac{}{}` | `a/b` → `\frac{a}{b}` |
| Roots → `\sqrt{}` | `√2` → `$\sqrt{2}$` |
| Vectors → `\vec{}`, unit → `\hat{}` | `A⃗` → `$\vec{A}$` |
| Chemical formulas → `\text{}` subscripts | `H2O` → `$\text{H}_2\text{O}$` |
| Greek letters → `\alpha`, `\beta`, … | inside `$…$` |

**Output:** `{"question": "...", "options": [{"identifier": "A", "content": "..."}, ...]}`

**Fallback:** If Gemini fails or returns malformed JSON, original text/options are returned unchanged.

---

### 5.5 TrendIntelligenceAgent

**Triggered:** Manually via `POST /recommender/admin/run-trend-update`  
**No LLM for scoring** — pure computation via `TrendScoreComputer`. LLM is used only for a brief anomaly log note (non-blocking async task).

**Pipeline:**
1. Aggregate `jee_mains_pyqs` collection → `year_matrix: {topic_id → {year → count}}`
2. For each topic: compute `raw`, `gap_bonus`, `streak_score`, `direction_mult`, `raw_combined`
3. Normalise all topics → `p_appears` via sigmoid
4. Upsert each result into `topic_trend_scores`
5. Async: send top-5 topics to `gemini-2.0-flash-lite` for a 1-2 sentence anomaly note (logged only)

---

## 6. Session Lifecycle

### Phase 1: Initialization (one-time)

`POST /recommender/initialize`

1. Load `prereqs_math.json` → insert one `student_topic_state` doc per Math topic (α=1, β=1, θ=0)
2. Query `jee_mains_pyqs` for distinct `(chapter, topic)` pairs per Physics and Chemistry subject → insert topic state docs (all unlocked since not in prereq graph)
3. Insert one `student_personality` doc with all defaults

---

### Phase 2: Session Start

`GET /recommender/session/start-stream` (SSE)

1. Load personality + last 3 session summaries
2. Run `SessionPlannerAgent` (tool-use loop, up to 5 rounds)
3. Stream step events to frontend as each tool completes
4. Return `SessionPlanResponse` containing `session_id`, `focus_topics`, `session_mode`, `start_difficulty_offset`, `review_injection_rate`, `confidence_note`

---

### Phase 3: Question Loop

Repeat for each question (N questions chosen by student):

**A.** `POST /session/next-question` → calls per-turn pipeline (§7)

**B.** `GET /recommender/question/{id}` → LatexConverterAgent renders KaTeX

**C.** Student answers

**D.** `POST /session/submit-answer`
   - IRT theta update
   - BKT (α/β) update
   - SM-2 / retry interval update
   - Prerequisite unlock check
   - Confidence Regulator evaluates new hot-state
   - If `consecutive_wrong ≥ 3` → spawn `DiagnosisAgent` async

---

### Phase 4: Session End

`POST /session/end`

1. Aggregate session events → `accuracy_by_chapter`, `avg_time_by_topic`, block accuracies
2. Insert `session_summary` document
3. Spawn `DiagnosisAgent` async (trigger = `"session_end"`)

---

## 7. Per-Turn Question Selection Pipeline

This is the complete decision tree executed for every `POST /session/next-question`:

```
Input: student_id, session_id, focus_topics, start_difficulty_offset,
       review_injection_rate, hot_state (consecutive_wrong, questions_asked, seen_ids)

Step 1: Confidence Regulator
─────────────────────────────
  mode = get_session_mode(consecutive_wrong, questions_asked, confidence_profile, fatigue_threshold)
  difficulty_offset = start_difficulty_offset + mode.difficulty_offset
  │
  ├─► mode = "recovery"   → difficulty_offset -= 1.0 (easy questions)
  │                          topic_override = "pick_mastered_topic"
  ├─► mode = "wind_down"  → difficulty_offset -= 0.5 (easier questions)
  └─► mode = "normal"     → no change

Step 2: Incorrect Retry Injection  [checked first, higher priority]
─────────────────────────────────────────────────────────────────────
  if random() < 0.55 AND mode == "normal":
    due_wrong = get_due_incorrect_questions(student_id, limit=5)
    candidates = [q for q in due_wrong if q.question_id NOT in seen_all_ids]
    if candidates:
      retry = candidates[0]    ← sorted by consecutive_incorrect DESC
      return NextQuestionResponse(
        question_id = retry.question_id,
        is_review_injection = True,
        review_reason = f"You got this wrong {n} times..."
      )

Step 3: SM-2 Review Injection  [correct questions, lower priority]
──────────────────────────────────────────────────────────────────
  if random() < review_injection_rate AND mode == "normal":
    due = get_due_review_questions(student_id, limit=5)
    candidates = [q for q in due if q.question_id NOT in seen_all_ids]
    if candidates:
      review = candidates[0]   ← sorted by next_review_date ASC (most overdue first)
      return NextQuestionResponse(
        question_id = review.question_id,
        is_review_injection = True,
        review_reason = f"You solved this {n} days ago..."
      )

Step 4: Topic Selection via Thompson Sampling
──────────────────────────────────────────────
  all_states = load all student topic states
  unlocked_set = { t | is_unlocked(t, all_states, prereq_graph) }

  if mode.topic_override == "pick_mastered_topic":
    candidates = states from strong_chapters ∩ unlocked_set
  else:
    candidates = states from focus_topics ∩ unlocked_set
                 (fallback: all unlocked states if intersection is empty)

  trend_scores = load p_appears for all topics
  target_topic = argmax_t { (1 − Beta(α_t, β_t).sample()) × trend_scores[t] }

Step 5: IRT Difficulty Targeting
──────────────────────────────────
  θ = topic_state[target_topic].theta
  d_target  = θ + 0.62 + difficulty_offset
  [d_min, d_max] = [d_target − 0.4, d_target + 0.4]

Step 6: Question Selection via QuestionSelectorAgent
─────────────────────────────────────────────────────
  candidates = query jee_mains_pyqs where:
    chapter == split(target_topic)[0]
    topic   == split(target_topic)[1]
    difficulty in [d_min, d_max]
    question_id NOT IN (seen_correct_ids ∪ solved_not_due)
    limit = 10

  if candidates is empty:
    retry with [−1.5, 1.5] and seen_correct_ids=[] (wide open)

  type_weights = compute question-type improvement priorities
  selected_id  = QuestionSelectorAgent.run(candidates, error_profile, type_weights)
                 (falls back to deterministic scoring if LLM fails)

Step 7: Return
──────────────
  return NextQuestionResponse(
    question_id        = selected_id,
    topic_id           = target_topic,
    chapter            = topic_state.chapter,
    difficulty_target  = round(d_target, 3),
    is_review_injection = False,
    session_mode       = mode.mode,
    difficulty_offset_applied = round(difficulty_offset, 3),
  )
```

---

## 8. Tuning Constants Reference

All values live in `backend/modules/recommender/constants.py`.

### IRT

| Constant | Value | Effect of increasing |
|----------|-------|---------------------|
| `IRT_LEARNING_RATE` | 0.3 | Faster θ updates (more reactive to each answer) |
| `IRT_ZPD_OFFSET` | 0.62 | Targets P(correct) ≈ 65%. Increase → harder questions |
| `difficulty_band half_width` | ±0.4 | Wider band → more question variety at a given difficulty |

### Thompson Sampling

| Constant | Value | Notes |
|----------|-------|-------|
| `THOMPSON_INITIAL_ALPHA` | 1 | Beta(1,1) = uniform prior |
| `THOMPSON_INITIAL_BETA` | 1 | |
| `MASTERY_THRESHOLD` | 0.75 | Lower → unlock topics earlier; higher → more gatekeeping |

### SM-2

| Constant | Value | Notes |
|----------|-------|-------|
| `SM2_DEFAULT_EASINESS_FACTOR` | 2.5 | Starting EF; good learners converge to ~2.5 |
| `SM2_MIN_EASINESS_FACTOR` | 1.3 | Hard floor; prevents intervals from growing too slowly |
| `SM2_FIRST_INTERVAL_DAYS` | 1 | First correct → come back tomorrow |
| `SM2_REVIEW_INJECTION_PROB` | 0.30 | 30% chance of showing a due review question each turn |

### Incorrect Retry

| Constant | Value | Notes |
|----------|-------|-------|
| `INCORRECT_FIRST_INTERVAL_DAYS` | 1 | Wrong → retry tomorrow |
| `INCORRECT_MAX_INTERVAL_DAYS` | 3 | Never waits more than 3 days |
| `INCORRECT_INJECTION_PROB` | 0.55 | Higher than SM-2 review; failures come back faster |
| `ATTEMPTED_EXCLUSION_DAYS` | 7 | Both correct and incorrect excluded for 7 days from normal pool |

### Confidence Regulator

| Constant | Value | Notes |
|----------|-------|-------|
| `REGULATOR_BRITTLE_FRUSTRATION_THRESHOLD` | 2 | Recovery after 2 consecutive wrong |
| `REGULATOR_NORMAL_FRUSTRATION_THRESHOLD` | 3 | Recovery after 3 consecutive wrong |
| `REGULATOR_RECOVERY_DIFFICULTY_OFFSET` | −1.0 | Significantly easier questions in recovery |
| `REGULATOR_FATIGUE_DIFFICULTY_OFFSET` | −0.5 | Slightly easier in wind-down |

### Error Taxonomy

| Constant | Value | Notes |
|----------|-------|-------|
| `ERROR_INCONSISTENCY_HIGH` | 0.6 | Above → computation error |
| `ERROR_CEILING_LOW` | −0.2 | Below → conceptual error |
| `ERROR_TIME_Z_HIGH` | 1.5 | Above → speed error |
| `AVOIDANCE_SCORE_THRESHOLD` | 0.5 | Flag topic for avoidance pattern |

### Trend Engine

| Constant | Value | Notes |
|----------|-------|-------|
| `TREND_DECAY_LAMBDA` | 0.35 | Half-life ~2 years for historical appearances |
| `TREND_START_YEAR` | 2014 | Historical data window start |
| `TREND_GAP_BONUS_PER_YEAR` | 0.25 | +25% weight per year a topic hasn't appeared |
| `TREND_GAP_BONUS_CAP` | 1.75 | Maximum gap bonus (caps at 3 years of absence) |
| `TREND_STREAK_BONUS_PER_YEAR` | 0.15 | +15% per consecutive year of appearance |
| `TREND_MAX_STREAK_YEARS` | 5 | Streak bonus caps at 5 years (+75%) |
| `TREND_DIRECTION_MAX_SLOPE` | 2.0 | Slope clipped to [−2, +2] |
| `TREND_DIRECTION_FACTOR` | 0.1 | 10% boost/penalty per unit slope |
| `TREND_SIGMOID_SHARPNESS` | 3.0 | Controls spread of p_appears distribution |
| `TREND_HIGH_PRIORITY_THRESHOLD` | 0.70 | p_appears ≥ 0.70 → shown as 🔥 hot topic |

---

*This document is auto-derived from the source code. When constants or formulas change, update the relevant section above.*
