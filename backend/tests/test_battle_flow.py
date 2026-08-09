import asyncio
import json
import os
import subprocess
import sys
import time
import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.jwt_handler import create_access_token

PORT = 8009
WS_URL = f"ws://127.0.0.1:{PORT}/api/v1/battle/ws"

async def player_client(name, user_id, answers_to_submit):
    token = create_access_token(subject=user_id)
    url = f"{WS_URL}?token={token}"
    print(f"[{name}] Connecting...")
    async with websockets.connect(url) as ws:
        print(f"[{name}] Connected!")
        async for raw_msg in ws:
            msg = json.loads(raw_msg)
            msg_type = msg.get("type")
            print(f"[{name}] -> {msg_type}")

            if msg_type == "question":
                qid = msg["question_id"]
                idx = msg["index"]
                selected = answers_to_submit[idx] if idx < len(answers_to_submit) else "A"
                await asyncio.sleep(0.2)
                print(f"[{name}] Submitting answer '{selected}' for question {idx+1}")
                await ws.send(json.dumps({"type": "submit_answer", "question_id": qid, "selected_option": selected}))

            elif msg_type in ("battle_complete", "error", "queue_timeout"):
                print(f"[{name}] Completed: result={msg.get('result')}, your_score={msg.get('your_score')}, opp_score={msg.get('opponent_score')}")
                break

async def run_clients():
    from config.redis import connect_to_redis, get_redis
    await connect_to_redis()
    r = get_redis()
    if r is not None:
        await r.delete("battle:active:6a141850192cef84947f422f")
        await r.delete("battle:active:6a1872ee9818813d78dfabae")
        await r.delete("battle:inbox:6a141850192cef84947f422f")
        await r.delete("battle:inbox:6a1872ee9818813d78dfabae")
        await r.delete("battle:queue")

    print("Connecting 2 concurrent battle players...")
    await asyncio.gather(
        player_client("Player 1", "6a141850192cef84947f422f", ["A", "B", "C", "D", "A"]),
        player_client("Player 2", "6a1872ee9818813d78dfabae", ["B", "A", "C", "A", "B"]),
    )

import httpx

def main():
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", str(PORT)],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    for _ in range(30):
        time.sleep(0.5)
        try:
            r = httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=1)
            if r.status_code == 200:
                print("Server is UP and Healthy!")
                break
        except Exception:
            pass
    try:
        asyncio.run(run_clients())
        print("\nSUCCESS: Battle completed end-to-end!")
    finally:
        server.terminate()
        server.kill()

if __name__ == "__main__":
    main()
