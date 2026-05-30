"""
Manual integration tests for the recommender API.
Run against a live backend: uvicorn main:app --reload --port 8000

Usage:
    python test_recommender_api.py
"""

import json
import requests

BASE = "http://localhost:8000/api/v1"
EMAIL = "srinjoy377@gmail.com"
PASSWORD = "123@Srinjoy"


def login() -> str:
    r = requests.post(f"{BASE}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    token = r.json()["tokens"]["access_token"]
    print(f"Logged in as {EMAIL}")
    return token


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def pretty(label: str, data: dict):
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    print(json.dumps(data, indent=2, default=str))


# --- individual test functions ---

def test_initialize(token: str):
    r = requests.post(f"{BASE}/recommender/initialize", headers=headers(token))
    pretty("Initialize student", r.json())
    return r.status_code


def test_get_personality(token: str):
    r = requests.get(f"{BASE}/recommender/personality", headers=headers(token))
    pretty("Personality", r.json())


def test_get_topic_states(token: str):
    r = requests.get(f"{BASE}/recommender/topic-states", headers=headers(token))
    data = r.json()
    print(f"\nTopic states: total={data.get('total')}, unlocked={data.get('unlocked_count')}")
    if data.get("topic_states"):
        print("First 3 topics:")
        for t in data["topic_states"][:3]:
            print(f"  {t['topic_id']}  mastery={t['mastery_mean']}  unlocked={t['is_unlocked']}")


def test_get_stats(token: str):
    r = requests.get(f"{BASE}/recommender/stats", headers=headers(token))
    pretty("Student stats", r.json())


def test_get_trends(token: str):
    r = requests.get(f"{BASE}/recommender/trends", headers=headers(token))
    data = r.json()
    print(f"\nTrend scores: total={data.get('total')}, high_priority={data.get('high_priority_count')}")
    if data.get("topics"):
        print("Top 3 topics by p_appears:")
        for t in data["topics"][:3]:
            print(f"  {t['topic_id']}  p_appears={t['p_appears']}  high_priority={t['is_high_priority']}")


def test_get_sessions(token: str):
    r = requests.get(f"{BASE}/recommender/sessions", headers=headers(token))
    data = r.json()
    print(f"\nSession history: total={data.get('total')}")


def test_start_session(token: str) -> dict:
    r = requests.post(f"{BASE}/recommender/session/start", headers=headers(token))
    r.raise_for_status()
    data = r.json()
    print(f"\nSession started: {data['session_id']}")
    print(f"  mode={data['session_mode']}  focus_topics={len(data['focus_topics'])}")
    print(f"  confidence_note: {data.get('confidence_note', '')}")
    if data.get("reasoning_steps"):
        print("  reasoning_steps:")
        for s in data["reasoning_steps"]:
            print(f"    - {s}")
    return data


def test_next_question(token: str, plan: dict) -> dict:
    payload = {
        "session_id": plan["session_id"],
        "focus_topics": plan["focus_topics"],
        "start_difficulty_offset": plan["start_difficulty_offset"],
        "review_injection_rate": plan["review_injection_rate"],
        "state": plan["state"],
    }
    r = requests.post(f"{BASE}/recommender/session/next-question", json=payload, headers=headers(token))
    r.raise_for_status()
    data = r.json()
    print(f"\nNext question: {data['question_id']}")
    print(f"  topic={data['topic_id']}  difficulty={data['difficulty_target']}  review={data['is_review_injection']}")
    return data


def test_get_question(token: str, question_id: str) -> dict:
    r = requests.get(f"{BASE}/recommender/question/{question_id}", headers=headers(token))
    r.raise_for_status()
    data = r.json()
    print(f"\nQuestion detail:")
    print(f"  chapter={data['chapter']}  topic={data['topic']}  difficulty={data['difficulty']}  year={data.get('year')}")
    print(f"  type={data['type']}")
    q_text = data["question"]
    print(f"  question (first 120 chars): {q_text[:120]}...")
    return data


def test_submit_answer(token: str, plan: dict, nq: dict, correct: bool = True) -> dict:
    payload = {
        "session_id": plan["session_id"],
        "question_id": nq["question_id"],
        "topic_id": nq["topic_id"],
        "chapter": nq["chapter"],
        "correct": correct,
        "time_ms": 45000,
        "difficulty": nq["difficulty_target"],
        "question_type": "single_correct",
        "state": plan["state"],
    }
    r = requests.post(f"{BASE}/recommender/session/submit-answer", json=payload, headers=headers(token))
    r.raise_for_status()
    data = r.json()
    print(f"\nAnswer submitted (correct={correct}):")
    ut = data["updated_topic"]
    print(f"  mastery_mean={ut['mastery_mean']}  theta={ut['theta']}")
    print(f"  newly_unlocked={data['newly_unlocked_topics']}")
    print(f"  frustration_triggered={data['frustration_triggered']}")
    return data


def test_end_session(token: str, plan: dict):
    import datetime
    payload = {
        "session_id": plan["session_id"],
        "state": plan["state"],
        "started_at": datetime.datetime.utcnow().isoformat() + "Z",
    }
    r = requests.post(f"{BASE}/recommender/session/end", json=payload, headers=headers(token))
    r.raise_for_status()
    data = r.json()
    print(f"\nSession ended: summary_id={data['summary_id']}  diagnosis_triggered={data['diagnosis_triggered']}")


def test_trend_update(token: str):
    r = requests.post(f"{BASE}/recommender/admin/run-trend-update", headers=headers(token))
    pretty("Trend update", r.json())


# --- main ---

if __name__ == "__main__":
    token = login()

    print("\n--- Static endpoints ---")
    test_get_personality(token)
    test_get_stats(token)
    test_get_trends(token)
    test_get_sessions(token)
    test_get_topic_states(token)

    print("\n--- Full session flow ---")
    plan = test_start_session(token)
    nq   = test_next_question(token, plan)
    qd   = test_get_question(token, nq["question_id"])

    # submit correct answer, update state for next call
    submit = test_submit_answer(token, plan, nq, correct=True)
    plan["state"] = submit["state"]

    # get another question with updated state
    nq2 = test_next_question(token, plan)
    test_get_question(token, nq2["question_id"])
    submit2 = test_submit_answer(token, plan, nq2, correct=False)

    test_end_session(token, plan)

    print("\nAll done.")
