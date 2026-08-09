"""Battle matchmaker — public API re-exports.

Consumers import from here exactly as they imported from the old
``modules.battle.matchmaker`` single file:

    from modules.battle.matchmaker import manager, Player, Battle

The module-level ``manager`` singleton is created here without Redis
(it starts in in-memory mode). The app lifespan in ``main.py`` calls
``init_matchmaker_redis()`` to late-bind the Upstash client once
``connect_to_redis()`` has established the connection.
"""

from modules.battle.matchmaker.manager import BattleMatchmaker  # noqa: F401
from modules.battle.matchmaker.models import Battle, Player  # noqa: F401

# Module-level singleton — imported by the controller and service.
# Starts in in-memory mode; ``init_matchmaker_redis()`` upgrades it.
manager = BattleMatchmaker()


def init_matchmaker_redis() -> None:
    """Inject the live Redis client into the manager.

    Called once from ``main.py`` lifespan after ``connect_to_redis()``.
    Safe to call when Redis is unconfigured (manager stays in-memory).
    """
    from config.redis import get_redis
    redis = get_redis()
    manager.set_redis(redis)
