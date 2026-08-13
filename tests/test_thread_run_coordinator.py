"""Single-flight ownership contracts for one LangGraph conversation."""

from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_new_turn_cancels_and_awaits_previous_turn_before_entering():
    from core.thread_run_coordinator import ThreadRunCoordinator

    coordinator = ThreadRunCoordinator()
    first_entered = asyncio.Event()
    first_cleaned = asyncio.Event()
    second_entered = asyncio.Event()

    async def first_turn():
        try:
            async with coordinator.run("same-thread", "message-1"):
                first_entered.set()
                await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            first_cleaned.set()

    async def second_turn():
        async with coordinator.run("same-thread", "message-2"):
            assert first_cleaned.is_set()
            second_entered.set()

    first_task = asyncio.create_task(first_turn())
    await first_entered.wait()
    await second_turn()

    assert first_task.cancelled()
    assert second_entered.is_set()


@pytest.mark.asyncio
async def test_different_threads_can_run_concurrently():
    from core.thread_run_coordinator import ThreadRunCoordinator

    coordinator = ThreadRunCoordinator()
    both_entered = asyncio.Event()
    entered: set[str] = set()

    async def turn(thread_id: str):
        async with coordinator.run(thread_id, f"message-{thread_id}"):
            entered.add(thread_id)
            if len(entered) == 2:
                both_entered.set()
            await both_entered.wait()

    await asyncio.wait_for(
        asyncio.gather(turn("thread-a"), turn("thread-b")), timeout=0.5
    )
    assert entered == {"thread-a", "thread-b"}


@pytest.mark.asyncio
async def test_new_turn_does_not_cancel_an_already_cancelling_cleanup_twice():
    from core.thread_run_coordinator import ThreadRunCoordinator

    coordinator = ThreadRunCoordinator()
    first_entered = asyncio.Event()
    cleanup_started = asyncio.Event()
    allow_cleanup = asyncio.Event()
    cleanup_interrupted = asyncio.Event()
    second_entered = asyncio.Event()

    async def first_turn():
        try:
            async with coordinator.run("same-thread", "message-1"):
                first_entered.set()
                await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            try:
                await allow_cleanup.wait()
            except asyncio.CancelledError:
                cleanup_interrupted.set()
                raise

    async def second_turn():
        async with coordinator.run("same-thread", "message-2"):
            second_entered.set()

    first_task = asyncio.create_task(first_turn())
    await first_entered.wait()
    first_task.cancel()  # SSE client disconnect
    await cleanup_started.wait()

    second_task = asyncio.create_task(second_turn())
    await asyncio.sleep(0)
    assert not cleanup_interrupted.is_set()

    allow_cleanup.set()
    await asyncio.gather(first_task, return_exceptions=True)
    await asyncio.wait_for(second_task, timeout=0.2)

    assert second_entered.is_set()
    assert not cleanup_interrupted.is_set()
