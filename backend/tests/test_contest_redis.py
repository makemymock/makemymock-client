"""Live integration test for Contest Redis Caching & Concurrency:
1. Real-time Leaderboard via Redis Sorted Sets (ZADD, ZREVRANK, composite scoring).
2. Atomic Submission Deduplication via Redis SETNX.
3. Live Participant Counter via Redis INCR.
4. Full HTTP API lifecycle on running backend (/enter -> /start -> /submit -> /result -> /leaderboard).
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
import httpx
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.redis import connect_to_redis, get_redis
from config.settings import settings
from core.jwt_handler import create_access_token
from modules.contest.redis_cache import (
    increment_participants,
    leaderboard_add,
    leaderboard_rank,
    leaderboard_total,
    leaderboard_top,
    try_claim_submission,
)

BASE_URL = "http://127.0.0.1:8000/api/v1"


async def setup_test_users_and_contest():
    """Create test users and an active live contest in MongoDB."""
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]
    users_col = db["users"]
    contests_col = db["contests"]
    questions_col = db["questions_public"]

    # 1. Setup Users
    p1 = await users_col.find_one({"email": "test_contest_p1@makemymock.com"})
    if not p1:
        res1 = await users_col.insert_one({
            "email": "test_contest_p1@makemymock.com",
            "username": "ContestPlayerOne",
            "is_active": True,
            "is_verified": True,
            "created_at": datetime.now(timezone.utc),
        })
        p1_id = res1.inserted_id
    else:
        p1_id = p1["_id"]
        await users_col.update_one({"_id": p1_id}, {"$set": {"is_active": True, "is_verified": True}})

    p2 = await users_col.find_one({"email": "test_contest_p2@makemymock.com"})
    if not p2:
        res2 = await users_col.insert_one({
            "email": "test_contest_p2@makemymock.com",
            "username": "ContestPlayerTwo",
            "is_active": True,
            "is_verified": True,
            "created_at": datetime.now(timezone.utc),
        })
        p2_id = res2.inserted_id
    else:
        p2_id = p2["_id"]
        await users_col.update_one({"_id": p2_id}, {"$set": {"is_active": True, "is_verified": True}})

    # 2. Fetch 3 sample questions
    qdocs = await questions_col.find({"questionType": "single_correct"}).limit(3).to_list(3)
    q_ids = [q["_id"] for q in qdocs]
    assert len(q_ids) > 0, "No sample questions found in questions_public"

    # 3. Create or update an active live contest
    now = datetime.now(timezone.utc)
    contest_doc = {
        "title": "Redis Live Performance Test Contest",
        "description": "Integration testing contest for Redis caching.",
        "rules": "Solve 3 questions.",
        "start_time": now - timedelta(minutes=5),
        "end_time": now + timedelta(hours=1),
        "duration_seconds": 1800,
        "question_ids": q_ids,
        "marking": {"correct": 4.0, "wrong": -1.0, "unattempted": 0.0},
        "created_at": now,
    }
    res_c = await contests_col.insert_one(contest_doc)
    contest_id = res_c.inserted_id

    client.close()

    token1 = create_access_token(str(p1_id))
    token2 = create_access_token(str(p2_id))

    return str(contest_id), str(p1_id), token1, str(p2_id), token2, qdocs


async def test_redis_cache_layer_directly():
    print("\n==================================================")
    print("TEST 1: Direct Redis Cache Module Verification")
    print("==================================================")

    await connect_to_redis()
    redis = get_redis()
    assert redis is not None, "Upstash Redis connection is not established"

    test_cid = f"test_direct_{ObjectId()}"
    u_alice = "user_alice"
    u_bob = "user_bob"
    u_charlie = "user_charlie"

    # 1. Participant Counter Test
    c1 = await increment_participants(redis, test_cid)
    c2 = await increment_participants(redis, test_cid)
    assert c1 == 1, f"Expected 1, got {c1}"
    assert c2 == 2, f"Expected 2, got {c2}"
    print(f"--> Participant INCR Counter: {c1} -> {c2} [PASSED]")

    # 2. Submission Deduplication Lock (SETNX)
    claim1 = await try_claim_submission(redis, test_cid, u_alice)
    claim2 = await try_claim_submission(redis, test_cid, u_alice)
    assert claim1 is True, "First submission claim should be True"
    assert claim2 is False, "Second submission claim must be False (deduplicated)"
    print("--> Submission SETNX Dedup: First=True, Second=False [PASSED]")

    # 3. Leaderboard Sorted Set (ZADD & Composite Scoring)
    # Alice: Score 50, Time 120s
    # Bob: Score 80, Time 60s  -> Should be Rank 1
    # Charlie: Score 50, Time 90s -> Should be Rank 2 (Same score as Alice, but faster time)
    # Alice: Should be Rank 3 (Same score as Charlie, but slower time)
    await leaderboard_add(redis, test_cid, u_alice, score=50.0, time_taken_seconds=120)
    await leaderboard_add(redis, test_cid, u_bob, score=80.0, time_taken_seconds=60)
    await leaderboard_add(redis, test_cid, u_charlie, score=50.0, time_taken_seconds=90)

    rank_bob = await leaderboard_rank(redis, test_cid, u_bob)
    rank_charlie = await leaderboard_rank(redis, test_cid, u_charlie)
    rank_alice = await leaderboard_rank(redis, test_cid, u_alice)
    total_users = await leaderboard_total(redis, test_cid)

    print(f"--> Bob Rank: {rank_bob} (Expected: 1) [Score: 80, Time: 60s]")
    print(f"--> Charlie Rank: {rank_charlie} (Expected: 2) [Score: 50, Time: 90s]")
    print(f"--> Alice Rank: {rank_alice} (Expected: 3) [Score: 50, Time: 120s]")
    print(f"--> Total Leaderboard Entries: {total_users} (Expected: 3)")

    assert rank_bob == 1, f"Expected Bob rank 1, got {rank_bob}"
    assert rank_charlie == 2, f"Expected Charlie rank 2, got {rank_charlie}"
    assert rank_alice == 3, f"Expected Alice rank 3, got {rank_alice}"
    assert total_users == 3, f"Expected 3, got {total_users}"

    top_list = await leaderboard_top(redis, test_cid, limit=5)
    print(f"--> Top entries from ZREVRANGE: {top_list}")
    assert len(top_list) == 3

    print("TEST 1 PASSED: Direct Redis cache layer behaves correctly!\n")


async def test_contest_http_api_flow(contest_id: str, p1_id: str, token1: str, p2_id: str, token2: str, qdocs: list):
    print("==================================================")
    print("TEST 2: Full Live Contest API Lifecycle with Redis")
    print("==================================================")

    async with httpx.AsyncClient() as client:
        h1 = {"Authorization": f"Bearer {token1}"}
        h2 = {"Authorization": f"Bearer {token2}"}

        # 1. Enter Lobby
        enter1 = await client.post(f"{BASE_URL}/contests/{contest_id}/enter", headers=h1)
        assert enter1.status_code == 200, f"Enter lobby failed: {enter1.text}"
        print(f"[Player 1] Entered lobby at {enter1.json().get('entered_at')}")

        enter2 = await client.post(f"{BASE_URL}/contests/{contest_id}/enter", headers=h2)
        assert enter2.status_code == 200, f"Enter lobby failed: {enter2.text}"
        print(f"[Player 2] Entered lobby at {enter2.json().get('entered_at')}")

        # 2. Start Contest
        start1 = await client.post(f"{BASE_URL}/contests/{contest_id}/start", headers=h1)
        assert start1.status_code == 200, f"Start failed: {start1.text}"
        q_payload = start1.json().get("questions", [])
        print(f"[Player 1] Started contest with {len(q_payload)} questions")

        start2 = await client.post(f"{BASE_URL}/contests/{contest_id}/start", headers=h2)
        assert start2.status_code == 200, f"Start failed: {start2.text}"
        print(f"[Player 2] Started contest")

        # 3. Player 1 Submits (Gets 1 correct, 2 unattempted -> Score: 4.0)
        p1_answers = [
            {"question_id": str(qdocs[0]["_id"]), "selected_option": qdocs[0].get("correctOption", "A")},
            {"question_id": str(qdocs[1]["_id"]), "selected_option": None},
            {"question_id": str(qdocs[2]["_id"]), "selected_option": None},
        ]
        sub1 = await client.post(
            f"{BASE_URL}/contests/{contest_id}/submit",
            headers=h1,
            json={"answers": p1_answers},
        )
        assert sub1.status_code == 200, f"Submit 1 failed: {sub1.text}"
        sub1_res = sub1.json()
        print(f"[Player 1] Submitted! Score: {sub1_res['score']}, Rank: {sub1_res['rank']}, Total: {sub1_res['total_participants']}")
        assert sub1_res["rank"] == 1

        # 4. Test Submission Deduplication (Player 1 attempts double-submit)
        double_sub = await client.post(
            f"{BASE_URL}/contests/{contest_id}/submit",
            headers=h1,
            json={"answers": p1_answers},
        )
        print(f"[Player 1] Double-submit attempt status code: {double_sub.status_code}")
        assert double_sub.status_code == 400 or double_sub.status_code == 409
        print(f"--> Double-submission rejected by Redis SETNX guard: {double_sub.json()} [PASSED]")

        # 5. Player 2 Submits with higher score (Gets all 3 correct -> Score: 12.0)
        p2_answers = [
            {"question_id": str(qdocs[0]["_id"]), "selected_option": qdocs[0].get("correctOption", "A")},
            {"question_id": str(qdocs[1]["_id"]), "selected_option": qdocs[1].get("correctOption", "A")},
            {"question_id": str(qdocs[2]["_id"]), "selected_option": qdocs[2].get("correctOption", "A")},
        ]
        sub2 = await client.post(
            f"{BASE_URL}/contests/{contest_id}/submit",
            headers=h2,
            json={"answers": p2_answers},
        )
        assert sub2.status_code == 200, f"Submit 2 failed: {sub2.text}"
        sub2_res = sub2.json()
        print(f"[Player 2] Submitted! Score: {sub2_res['score']}, Rank: {sub2_res['rank']}, Total: {sub2_res['total_participants']}")
        assert sub2_res["rank"] == 1, "Player 2 should now be Rank 1"

        # 6. Check Player 1 result update
        res1 = await client.get(f"{BASE_URL}/contests/{contest_id}/result", headers=h1)
        assert res1.status_code == 200
        p1_updated = res1.json()
        print(f"[Player 1] Fetched result: Rank is now {p1_updated['rank']}/{p1_updated['total_participants']} (Expected: 2/2)")
        assert p1_updated["rank"] == 2

        # 7. Check Leaderboard
        lb = await client.get(f"{BASE_URL}/contests/{contest_id}/leaderboard", headers=h1)
        assert lb.status_code == 200
        lb_data = lb.json()
        print(f"Leaderboard top rows: {[(r['rank'], r['username'], r['score']) for r in lb_data.get('rows', [])]}")
        assert len(lb_data.get("rows", [])) == 2
        assert lb_data["rows"][0]["username"] == "ContestPlayerTwo"
        assert lb_data["rows"][1]["username"] == "ContestPlayerOne"

        print("TEST 2 PASSED: Full contest API with Redis caching and dedup verified!\n")


async def main():
    print("Starting Contest Redis Cache Test Suite...")
    contest_id, p1_id, token1, p2_id, token2, qdocs = await setup_test_users_and_contest()

    # Test 1: Direct Redis operations
    await test_redis_cache_layer_directly()

    # Test 2: Live HTTP API flow
    await test_contest_http_api_flow(contest_id, p1_id, token1, p2_id, token2, qdocs)

    print("**************************************************")
    print("ALL CONTEST REDIS TESTS PASSED SUCCESSFULLY!")
    print("**************************************************")


if __name__ == "__main__":
    asyncio.run(main())
