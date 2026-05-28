// Sample data used by the Analytics page while its product tour is
// active, so brand-new users (with no test history yet) can see the
// full feature in action. Values are picked to look plausible, not
// aspirational — the page reverts to real data the moment the tour
// closes.

const DAY_MS = 24 * 60 * 60 * 1000;
const today = () => new Date();
const isoDaysAgo = (n) => new Date(today().getTime() - n * DAY_MS).toISOString();
const yyyyMmDdDaysAgo = (n) => isoDaysAgo(n).slice(0, 10);

const TREND = [
  { completed_at: isoDaysAgo(28), accuracy_pct: 52, score: 11.5 },
  { completed_at: isoDaysAgo(24), accuracy_pct: 58, score: 12.8 },
  { completed_at: isoDaysAgo(21), accuracy_pct: 55, score: 12.2 },
  { completed_at: isoDaysAgo(17), accuracy_pct: 63, score: 14.6 },
  { completed_at: isoDaysAgo(14), accuracy_pct: 61, score: 14.0 },
  { completed_at: isoDaysAgo(10), accuracy_pct: 68, score: 16.1 },
  { completed_at: isoDaysAgo(7),  accuracy_pct: 66, score: 15.7 },
  { completed_at: isoDaysAgo(5),  accuracy_pct: 72, score: 17.4 },
  { completed_at: isoDaysAgo(2),  accuracy_pct: 70, score: 17.0 },
  { completed_at: isoDaysAgo(0),  accuracy_pct: 74, score: 18.2 },
];

const WEAKEST_TOPICS = [
  { topic_id: 'd-w-1', topic_name: 'Rotational Dynamics',  subject_name: 'Physics',   chapter_name: 'Rotational Motion',     priority_score: 0.83, accuracy_pct: 42, attempts: 8 },
  { topic_id: 'd-w-2', topic_name: 'Probability — Bayes',  subject_name: 'Maths',     chapter_name: 'Probability',            priority_score: 0.79, accuracy_pct: 45, attempts: 6 },
  { topic_id: 'd-w-3', topic_name: 'Aldol Condensation',   subject_name: 'Chemistry', chapter_name: 'Aldehydes & Ketones',    priority_score: 0.74, accuracy_pct: 48, attempts: 5 },
  { topic_id: 'd-w-4', topic_name: 'Vector Triple Product',subject_name: 'Maths',     chapter_name: 'Vectors',                priority_score: 0.71, accuracy_pct: 50, attempts: 4 },
  { topic_id: 'd-w-5', topic_name: 'Capacitors — RC Decay',subject_name: 'Physics',   chapter_name: 'Current Electricity',    priority_score: 0.68, accuracy_pct: 52, attempts: 7 },
];

const STRONGEST_TOPICS = [
  { topic_id: 'd-s-1', topic_name: 'Kinematics — 1D',        subject_name: 'Physics',   chapter_name: 'Motion in a Line',    accuracy_pct: 92, attempts: 14, priority_score: 0.12 },
  { topic_id: 'd-s-2', topic_name: 'Quadratic Equations',    subject_name: 'Maths',     chapter_name: 'Algebra',             accuracy_pct: 89, attempts: 18, priority_score: 0.15 },
  { topic_id: 'd-s-3', topic_name: 'Periodic Properties',    subject_name: 'Chemistry', chapter_name: 'Periodic Table',      accuracy_pct: 87, attempts: 11, priority_score: 0.18 },
  { topic_id: 'd-s-4', topic_name: 'Trigonometric Identities',subject_name: 'Maths',    chapter_name: 'Trigonometry',        accuracy_pct: 85, attempts: 16, priority_score: 0.20 },
  { topic_id: 'd-s-5', topic_name: "Newton's Laws",          subject_name: 'Physics',   chapter_name: 'Laws of Motion',      accuracy_pct: 83, attempts: 13, priority_score: 0.22 },
];

export const DUMMY_OVERVIEW = {
  total_tests: 12,
  total_questions: 384,
  overall_accuracy_pct: 64.3,
  total_score: 168.4,
  trend: TREND,
  by_difficulty: [
    { difficulty: 'easy',   attempts: 162, accuracy_pct: 78.4 },
    { difficulty: 'medium', attempts: 158, accuracy_pct: 61.2 },
    { difficulty: 'hard',   attempts: 64,  accuracy_pct: 41.6 },
  ],
  by_type: [
    { question_type: 'single_correct', attempts: 198 },
    { question_type: 'multi_correct',  attempts: 72  },
    { question_type: 'integer',        attempts: 48  },
    { question_type: 'matching',       attempts: 32  },
    { question_type: 'passage',        attempts: 34  },
  ],
  weakest_topics: WEAKEST_TOPICS,
  strongest_topics: STRONGEST_TOPICS,
};

export const DUMMY_CHAPTERS = {
  chapters: [
    { chapter_id: 'd-ch-1', subject_name: 'Physics',   chapter_name: 'Rotational Motion',    accuracy_pct: 52, avg_priority_score: 0.74, attempts: 28, attempted_topic_count: 5, total_topic_count: 8 },
    { chapter_id: 'd-ch-2', subject_name: 'Maths',     chapter_name: 'Probability',          accuracy_pct: 58, avg_priority_score: 0.66, attempts: 22, attempted_topic_count: 4, total_topic_count: 6 },
    { chapter_id: 'd-ch-3', subject_name: 'Chemistry', chapter_name: 'Aldehydes & Ketones',  accuracy_pct: 61, avg_priority_score: 0.58, attempts: 18, attempted_topic_count: 3, total_topic_count: 5 },
    { chapter_id: 'd-ch-4', subject_name: 'Maths',     chapter_name: 'Vectors',              accuracy_pct: 66, avg_priority_score: 0.52, attempts: 20, attempted_topic_count: 4, total_topic_count: 5 },
    { chapter_id: 'd-ch-5', subject_name: 'Physics',   chapter_name: 'Current Electricity',  accuracy_pct: 72, avg_priority_score: 0.41, attempts: 24, attempted_topic_count: 6, total_topic_count: 7 },
    { chapter_id: 'd-ch-6', subject_name: 'Physics',   chapter_name: 'Motion in a Line',     accuracy_pct: 88, avg_priority_score: 0.18, attempts: 30, attempted_topic_count: 4, total_topic_count: 4 },
  ],
};

export const DUMMY_TOPICS = {
  // Used by the page's masteredCount / needsWorkCount memos.
  topics: [
    ...WEAKEST_TOPICS,
    ...STRONGEST_TOPICS,
    // Pad with a few mid-range so the counts feel like a real mix.
    { topic_id: 'd-m-1', topic_name: 'Calorimetry',       subject_name: 'Physics',   chapter_name: 'Heat',          accuracy_pct: 64, attempts: 5 },
    { topic_id: 'd-m-2', topic_name: 'Mole Concept',      subject_name: 'Chemistry', chapter_name: 'Stoichiometry', accuracy_pct: 71, attempts: 6 },
    { topic_id: 'd-m-3', topic_name: 'Definite Integrals',subject_name: 'Maths',     chapter_name: 'Calculus',      accuracy_pct: 76, attempts: 8 },
  ],
};

export const DUMMY_HEATMAP = (() => {
  // 60 days of varied activity, biased toward more recent days.
  const days = [];
  for (let i = 60; i >= 0; i--) {
    const dayOfWeek = new Date(today().getTime() - i * DAY_MS).getDay();
    // weekends slightly busier, plus a recency bump
    let base = (i < 21 ? 2 : 1);
    if (dayOfWeek === 0 || dayOfWeek === 6) base += 1;
    const jitter = ((i * 7) % 5);
    const count = Math.max(0, base + jitter - 2);
    days.push({ date: yyyyMmDdDaysAgo(i), count });
  }
  const max_count = days.reduce((m, d) => Math.max(m, d.count), 0);
  return { days, max_count };
})();

// Shape matches what ConfidenceTrophy reads: data.tier.{name,min_score,max_score},
// data.score (0–100), data.next_tier.{name,min_score}.
export const DUMMY_CONFIDENCE = {
  score: 58,
  tier: { name: 'Confident', min_score: 40, max_score: 60 },
  next_tier: { name: 'Focused', min_score: 60 },
};
