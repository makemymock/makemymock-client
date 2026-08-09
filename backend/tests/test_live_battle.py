import asyncio
import json
import os
import sys
import httpx
import websockets
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_URL = "https://makemymock-backend-haltd572ca-el.a.run.app"
WS_URL = "wss://makemymock-backend-haltd572ca-el.a.run.app/api/v1/battle/ws"

async def login(email, password):
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{BASE_URL}/api/v1/auth/login", json={"email": email, "password": password})
        if r.status_code != 200:
            print(f"Login failed for {email}: {r.status_code} {r.text}")
            return None
        return r.json()["tokens"]["access_token"]

async def test_ws_client(name, token):
    url = f"{WS_URL}?token={token}"
    print(f"[{name}] Connecting to {url[:60]}...")
    try:
        async with websockets.connect(url) as ws:
            print(f"[{name}] WS Connected!")
            async for msg in ws:
                data = json.loads(msg)
                print(f"[{name}] Received: {data}")
                if data.get("type") in ("matched", "queue_timeout", "error"):
                    break
    except Exception as e:
        print(f"[{name}] Exception: {e}")

from core.jwt_handler import create_access_token

async def main():
    t1 = await login("srinjoydas566@gmail.com", "123@Srinjoy")
    # Generate token for another verified user: Aryan (6a1872ee9818813d78dfabae)
    t2 = create_access_token(subject="6a1872ee9818813d78dfabae")
    print("User 1 Token OK:", bool(t1))
    print("User 2 Token OK:", bool(t2))

    print("\n--- Connecting Player 1 and Player 2 to Public Queue ---")
    await asyncio.gather(
        test_ws_client("Player 1", t1),
        test_ws_client("Player 2", t2),
    )

if __name__ == "__main__":
    asyncio.run(main())
