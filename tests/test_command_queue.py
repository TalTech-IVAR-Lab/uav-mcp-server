"""Tests for server-side command queue."""

from __future__ import annotations

import asyncio
from time import monotonic

import pytest

from uav_mcp_server.command_queue import CommandQueue, QueueEntry
from uav_mcp_server.types import CommandResult, ErrorCode


def _make_entry(
    name: str = "test_cmd",
    result: CommandResult | None = None,
    *,
    delay_s: float = 0.0,
    source: str = "mcp",
) -> QueueEntry:
    async def runner() -> CommandResult:
        if delay_s > 0:
            await asyncio.sleep(delay_s)
        return result or CommandResult.ok(f"{name} executed.")

    loop = asyncio.get_running_loop()
    return QueueEntry(
        command_name=name,
        runner=runner,
        future=loop.create_future(),
        source=source,
    )


@pytest.mark.asyncio
async def test_sequential_execution() -> None:
    queue = CommandQueue(max_depth=10, rate_limit_per_sec=100)
    order: list[str] = []

    async def make_runner(name: str) -> CommandResult:
        order.append(name)
        return CommandResult.ok(name)

    loop = asyncio.get_running_loop()
    entries = [
        QueueEntry(command_name=n, runner=lambda n=n: make_runner(n), future=loop.create_future())
        for n in ("a", "b", "c")
    ]

    results = await asyncio.gather(*(queue.enqueue(e) for e in entries))

    assert [r.message for r in results] == ["a", "b", "c"]
    assert order == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_rate_delay_respected() -> None:
    rate = 5
    queue = CommandQueue(max_depth=10, rate_limit_per_sec=rate)
    expected_delay = 1.0 / rate

    timestamps: list[float] = []

    async def recording_runner() -> CommandResult:
        timestamps.append(monotonic())
        return CommandResult.ok("ok")

    loop = asyncio.get_running_loop()
    entries = [
        QueueEntry(command_name="cmd", runner=recording_runner, future=loop.create_future())
        for _ in range(3)
    ]
    await asyncio.gather(*(queue.enqueue(e) for e in entries))

    for i in range(1, len(timestamps)):
        assert timestamps[i] - timestamps[i - 1] >= expected_delay * 0.9


@pytest.mark.asyncio
async def test_queue_full_returns_error() -> None:
    queue = CommandQueue(max_depth=2, rate_limit_per_sec=1)

    async def slow_runner() -> CommandResult:
        await asyncio.sleep(10)
        return CommandResult.ok("done")

    loop = asyncio.get_running_loop()
    entries = [
        QueueEntry(command_name="slow", runner=slow_runner, future=loop.create_future())
        for _ in range(4)
    ]

    tasks = [asyncio.create_task(queue.enqueue(e)) for e in entries]
    await asyncio.sleep(0.05)

    results = []
    for t in tasks:
        if t.done():
            results.append(t.result())
        else:
            t.cancel()

    queue_full = [r for r in results if r.error_code == ErrorCode.QUEUE_FULL]
    assert len(queue_full) >= 1


@pytest.mark.asyncio
async def test_stop_and_clear() -> None:
    queue = CommandQueue(max_depth=10, rate_limit_per_sec=1)

    async def slow_runner() -> CommandResult:
        await asyncio.sleep(10)
        return CommandResult.ok("done")

    loop = asyncio.get_running_loop()
    first = QueueEntry(command_name="first", runner=slow_runner, future=loop.create_future())
    second = QueueEntry(command_name="second", runner=slow_runner, future=loop.create_future())
    third = QueueEntry(command_name="third", runner=slow_runner, future=loop.create_future())

    first_task = asyncio.create_task(queue.enqueue(first))
    second_task = asyncio.create_task(queue.enqueue(second))
    third_task = asyncio.create_task(queue.enqueue(third))

    await asyncio.sleep(0.05)
    summary = await queue.stop_and_clear()

    assert summary["cleared_count"] >= 1
    assert isinstance(summary["cancelled_commands"], list)

    for task in (first_task, second_task, third_task):
        if not task.done():
            task.cancel()


@pytest.mark.asyncio
async def test_status_reports_depth() -> None:
    queue = CommandQueue(max_depth=10, rate_limit_per_sec=1)

    async def slow_runner() -> CommandResult:
        await asyncio.sleep(5)
        return CommandResult.ok("done")

    loop = asyncio.get_running_loop()
    entries = [
        QueueEntry(command_name="cmd", runner=slow_runner, future=loop.create_future())
        for _ in range(3)
    ]
    tasks = [asyncio.create_task(queue.enqueue(e)) for e in entries]
    await asyncio.sleep(0.05)

    status = queue.status()
    assert status["max_depth"] == 10
    assert status["worker_running"] is True
    assert "pending_count" in status

    for t in tasks:
        t.cancel()


@pytest.mark.asyncio
async def test_runner_exception_handled() -> None:
    queue = CommandQueue(max_depth=10, rate_limit_per_sec=100)

    async def failing_runner() -> CommandResult:
        raise RuntimeError("Simulated failure")

    loop = asyncio.get_running_loop()
    entry = QueueEntry(command_name="bad_cmd", runner=failing_runner, future=loop.create_future())
    result = await queue.enqueue(entry)

    assert result.success is False
    assert result.error_code == ErrorCode.BACKEND_ERROR
    assert "Simulated failure" in result.message


@pytest.mark.asyncio
async def test_shutdown_cancels_pending() -> None:
    queue = CommandQueue(max_depth=10, rate_limit_per_sec=1)

    async def slow_runner() -> CommandResult:
        await asyncio.sleep(10)
        return CommandResult.ok("done")

    loop = asyncio.get_running_loop()
    entry = QueueEntry(command_name="cmd", runner=slow_runner, future=loop.create_future())
    task = asyncio.create_task(queue.enqueue(entry))
    await asyncio.sleep(0.05)
    await queue.shutdown()

    if not task.done():
        task.cancel()
