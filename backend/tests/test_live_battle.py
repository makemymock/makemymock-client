"""Live integration test for Battle Matchmaking (Public Queue & Friend Invite)
over active WebSockets and Upstash Redis.
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
import websockets
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from config.settings import settings
from core.jwt_handler import create_access_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("battle_test")

BASE_URL = "http://127.0.0.1:8000/api/v1"
WS_URL = "ws://127.0.0.1:8000/api/v1/battle/ws"


async def setup_test_users():
    """Ensure two verified test users exist in MongoDB."""
    client = AsyncIOMotorClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]
    users_col = db["users"]

    # Player 1
    p1 = await users_col.find_one({"email": "test_player_1@makemymock.com"})
    if not p1:
        doc1 = {
            "email": "test_player_1@makemymock.com",
            "username": "TestPlayerOne",
            "is_active": True,
            "is_verified": True,
            "created_at": datetime.now(timezone.utc),
        }
        res1 = await users_col.insert_one(doc1)
        p1_id = res1.inserted_id
    else:
        p1_id = p1["_id"]
        await users_col.update_one({"_id": p1_id}, {"$set": {"is_active": True, "is_verified": True}})

    # Player 2
    p2 = await users_col.find_one({"email": "test_player_2@makemymock.com"})
    if not p2:
        doc2 = {
            "email": "test_player_2@makemymock.com",
            "username": "TestPlayerTwo",
            "is_active": True,
            "is_verified": True,
            "created_at": datetime.now(timezone.utc),
        }
        res2 = await users_col.insert_one(doc2)
        p2_id = res2.inserted_id
    else:
        p2_id = p2["_id"]
        await users_col.update_one({"_id": p2_id}, {"$set": {"is_active": True, "is_verified": True}})

    client.close()
    token1 = create_access_token(str(p1_id))
    token2 = create_access_token(str(p2_id))
    return str(p1_id), token1, str(p2_id), token2


async def test_public_matchmaking(token1: str, token2: str):
    logger.info("==================================================")
    logger.info("TEST 1: Public 1-vs-1 Matchmaking & Full Battle")
    logger.info("==================================================")

    url1 = f"{WS_URL}?token={token1}"
    url2 = f"{WS_URL}?token={token2}"

    async with websockets.connect(url1) as ws1:
        msg1 = json.loads(await ws1.recv())
        logger.info("[Player 1] Received: %s", msg1)
        assert msg1.get("type") == "queued", f"Expected queued, got {msg1}"

        # Player 2 connects to trigger the match
        async with websockets.connect(url2) as ws2:
            msg2_queued = json.loads(await ws2.recv())
            logger.info("[Player 2] Received: %s", msg2_queued)

            # Both should now receive 'matched'
            msg1_matched = json.loads(await ws1.recv())
            msg2_matched = json.loads(await ws2.recv())
            logger.info("[Player 1] Matched event: %s", msg1_matched)
            logger.info("[Player 2] Matched event: %s", msg2_matched)

            assert msg1_matched.get("type") == "matched"
            assert msg2_matched.get("type") == "matched"
            assert msg1_matched.get("battle_id") == msg2_matched.get("battle_id")
            battle_id = msg1_matched.get("battle_id")

            # Handle countdown frames and question rounds
            rounds_played = 0
            while True:
                try:
                    # Player 1 and Player 2 receive messages
                    m1 = json.loads(await ws1.recv())
                    m2 = json.loads(await ws2.recv())

                    if m1.get("type") == "countdown":
                        logger.info("Countdown: %s", m1.get("value"))
                        continue

                    if m1.get("type") == "question":
                        rounds_played += 1
                        qid = m1.get("question_id")
                        idx = m1.get("index")
                        total = m1.get("total")
                        logger.info("--> Round %d/%d (QID: %s)", idx + 1, total, qid)

                        # Player 1 submits option A
                        await ws1.send(json.dumps({
                            "type": "submit_answer",
                            "question_id": qid,
                            "selected_option": "A",
                        }))

                        # Player 2 submits option B
                        await ws2.send(json.dumps({
                            "type": "submit_answer",
                            "question_id": qid,
                            "selected_option": "B",
                        }))

                    elif m1.get("type") == "opponent_answered" or m2.get("type") == "opponent_answered":
                        logger.info("Notification: opponent_answered received")

                    elif m1.get("type") == "question_result":
                        logger.info("[Player 1 Result] Correct: %s, Score: %d (Delta: +%d)",
                                    m1.get("your_correct"), m1.get("your_total_score"), m1.get("your_score_delta"))
                        logger.info("[Player 2 Result] Correct: %s, Score: %d (Delta: +%d)",
                                    m2.get("your_correct"), m2.get("your_total_score"), m2.get("your_score_delta"))

                    elif m1.get("type") == "battle_complete":
                        logger.info("==================================================")
                        logger.info("BATTLE COMPLETE! Result: P1: %s (%d pts), P2: %s (%d pts)",
                                    m1.get("result"), m1.get("your_score"),
                                    m2.get("result"), m2.get("your_score"))
                        logger.info("==================================================")
                        assert m1.get("battle_id") == battle_id
                        break

                except websockets.exceptions.ConnectionClosed:
                    break

            assert rounds_played > 0, "No question rounds were played"
            logger.info("TEST 1 PASSED: Successfully matched and played full 1v1 battle!\n")


async def test_duplicate_session_prevention(token1: str):
    logger.info("==================================================")
    logger.info("TEST 2: Duplicate Tab / Session Slot Prevention")
    logger.info("==================================================")

    url = f"{WS_URL}?token={token1}"

    async with websockets.connect(url) as ws_primary:
        msg1 = json.loads(await ws_primary.recv())
        assert msg1.get("type") == "queued"
        logger.info("[Tab 1] Successfully claimed slot and entered queue")

        # Open Tab 2 with the same token
        try:
            async with websockets.connect(url) as ws_duplicate:
                msg2 = json.loads(await ws_duplicate.recv())
                logger.info("[Tab 2] Received: %s", msg2)
                assert msg2.get("type") == "error"
                assert "already in a battle" in msg2.get("message", "").lower()
                logger.info("TEST 2 PASSED: Duplicate session was rejected cleanly!\n")
        except websockets.exceptions.ConnectionClosed as e:
            logger.info("Duplicate WS closed with code %s", e.code)


async def test_friend_invite_flow(token1: str, token2: str):
    logger.info("==================================================")
    logger.info("TEST 3: Battle-a-Friend Private Invite Flow")
    logger.info("==================================================")

    # 1. Create invite via REST
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{BASE_URL}/battle/invites",
            headers={"Authorization": f"Bearer {token1}"},
        )
        assert res.status_code == 201, f"Failed to create invite: {res.text}"
        invite_data = res.json()
        code = invite_data["code"]
        logger.info("Created private invite code: %s", code)

        # 2. Friend prechecks invite
        precheck = await client.post(
            f"{BASE_URL}/battle/invites/{code}/precheck",
            headers={"Authorization": f"Bearer {token2}"},
        )
        assert precheck.status_code == 200, f"Precheck failed: {precheck.text}"
        assert precheck.json().get("ready") is True
        logger.info("Friend precheck verified code %s", code)

    # 3. Both connect to WS with ?invite_code=...
    url1 = f"{WS_URL}?token={token1}&invite_code={code}"
    url2 = f"{WS_URL}?token={token2}&invite_code={code}"

    async with websockets.connect(url1) as ws1:
        msg1 = json.loads(await ws1.recv())
        assert msg1.get("type") == "queued"
        logger.info("[Host] Parked with invite code %s", code)

        async with websockets.connect(url2) as ws2:
            msg2 = json.loads(await ws2.recv())
            assert msg2.get("type") == "queued"
            logger.info("[Friend] Connected with invite code %s", code)

            # Both receive matched
            m1_match = json.loads(await ws1.recv())
            m2_match = json.loads(await ws2.recv())
            logger.info("[Host] Matched: %s", m1_match)
            logger.info("[Friend] Matched: %s", m2_match)
            assert m1_match.get("type") == "matched"
            assert m2_match.get("type") == "matched"
            assert m1_match.get("battle_id") == m2_match.get("battle_id")

            logger.info("TEST 3 PASSED: Private invite pair-up succeeded!\n")


async def main():
    logger.info("Setting up test users in MongoDB...")
    p1_id, token1, p2_id, token2 = await setup_test_users()
    logger.info("Test users ready: P1 (%s), P2 (%s)", p1_id, p2_id)

    # Run tests
    await test_public_matchmaking(token1, token2)
    await asyncio.sleep(0.5)
    await test_duplicate_session_prevention(token1)
    await asyncio.sleep(0.5)
    await test_friend_invite_flow(token1, token2)

    logger.info("**************************************************")
    logger.info("ALL BATTLE INTEGRATION TESTS PASSED SUCCESSFULLY!")
    logger.info("**************************************************")


if __name__ == "__main__":
    asyncio.run(main())
