"""Redis key builders for the battle matchmaker.

Single source of truth for every key pattern. Prevents typos and makes
it easy to grep the full key space. TTL values are documented alongside
the keys they protect.
"""

# ── TTL constants (seconds) ──────────────────────────────────────────
SLOT_TTL = 600          # 10 min — safety net for server crashes
QUEUE_MEMBER_TTL = 120  # 2 min — slightly longer than QUEUE_TIMEOUT_SECONDS
INVITE_TTL = 600        # 10 min — matches INVITE_TTL_MINUTES in model.py


# ── Slot management ──────────────────────────────────────────────────

def active_slot(user_id: str) -> str:
    """``battle:active:{user_id}`` — SETNX lock preventing duplicate
    tabs / connections for the same user."""
    return f"battle:active:{user_id}"


# ── Public matchmaking queue ─────────────────────────────────────────

QUEUE_KEY = "battle:queue"


"""Redis List holding JSON-encoded ``{user_id, username}`` entries in
FIFO order."""


def queue_membership(user_id: str) -> str:
    """``battle:queue:user:{user_id}`` — set when a user is pushed
    onto the queue so we can do O(1) membership checks (Redis List
    has no built-in ``LCONTAINS``)."""
    
    return f"battle:queue:user:{user_id}"


# ── Invite pairing ───────────────────────────────────────────────────

def invite_host(code: str) -> str:
    """``battle:invite:{code}`` — Hash storing the host's user_id and
    username while they wait for their friend to join."""
    return f"battle:invite:{code}"


# ── Distributed Battle Coordination ──────────────────────────────────

INBOX_TTL = 300           # 5 min
BATTLE_SESSION_TTL = 600  # 10 min


def player_inbox(user_id: str) -> str:
    """``battle:inbox:{user_id}`` — Redis List holding incoming messages/events
    for this player from remote coordinator containers."""
    return f"battle:inbox:{user_id}"


def battle_state_key(battle_id: str) -> str:
    """``battle:state:{battle_id}`` — Shared battle state across containers."""
    return f"battle:state:{battle_id}"


def battle_round_answers(battle_id: str, round_idx: int) -> str:
    """``battle:{battle_id}:round:{round_idx}:ans`` — Hash storing player answers
    for round_idx (keys: 'a', 'b')."""
    return f"battle:{battle_id}:round:{round_idx}:ans"

