"""Smoke test — ChapterLockManager gives the same lock for the same chapter
and different locks for different chapters."""

import asyncio

import pytest

from modules.pattern_miner.pipeline import ChapterLockManager


@pytest.mark.asyncio
async def test_same_chapter_returns_same_lock():
    mgr = ChapterLockManager()
    a = await mgr.for_chapter("probability")
    b = await mgr.for_chapter("probability")
    assert a is b


@pytest.mark.asyncio
async def test_different_chapters_get_different_locks():
    mgr = ChapterLockManager()
    a = await mgr.for_chapter("probability")
    b = await mgr.for_chapter("optics")
    assert a is not b


@pytest.mark.asyncio
async def test_lock_actually_serialises():
    mgr = ChapterLockManager()
    order: list[str] = []

    async def worker(name: str, hold: float) -> None:
        lock = await mgr.for_chapter("probability")
        async with lock:
            order.append(f"{name}-enter")
            await asyncio.sleep(hold)
            order.append(f"{name}-exit")

    await asyncio.gather(worker("A", 0.05), worker("B", 0.01))
    # Whichever entered first must also exit first — the lock is mutually exclusive.
    assert order[0].endswith("-enter")
    assert order[1].endswith("-exit")
    assert order[0][:1] == order[1][:1]
