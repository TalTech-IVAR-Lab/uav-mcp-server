"""Server-side command queue for sequential MCP tool execution.

When an AI client sends multiple tool calls in parallel, this queue buffers
them and executes them one at a time. Each caller awaits a Future that
resolves when its command actually executes, so callers receive a real
CommandResult rather than an immediate rejection.

Commands in QUEUE_BYPASS_COMMANDS (read-only and safety-critical) skip the
queue and execute immediately.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

from uav_mcp_server.types import CommandResult, ErrorCode


@dataclass
class QueueEntry:
    command_name: str
    runner: Callable[[], Awaitable[CommandResult]]
    future: asyncio.Future[CommandResult]
    enqueued_at: float = field(default_factory=monotonic)
    source: str = "mcp"


class CommandQueue:
    """FIFO command queue with sequential execution and rate-pacing.

    Commands are executed one at a time with a configurable delay between
    them. The delay mirrors the server's rate limit so the safety validator's
    rate limiter never fires for queued commands.

    The queue is per-server and shared across all clients (MCP and dashboard).
    """

    def __init__(self, *, max_depth: int = 10, rate_limit_per_sec: int = 2) -> None:
        self._queue: asyncio.Queue[QueueEntry] = asyncio.Queue(maxsize=max_depth)
        self._max_depth = max_depth
        self._rate_delay_s = 1.0 / rate_limit_per_sec
        self._worker_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Spawn the background worker. Call once after the event loop starts."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker(), name="command-queue-worker")

    async def shutdown(self) -> None:
        """Cancel the worker and drain any remaining entries."""
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
        await self._cancel_all_pending("Server is shutting down.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(self, entry: QueueEntry) -> CommandResult:
        """Add a command to the queue and wait for its result.

        Returns immediately with QUEUE_FULL if the queue is at capacity.
        Otherwise blocks until the command executes and returns its result.
        """
        self.start()  # lazy start — safe to call multiple times

        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            return CommandResult.fail(
                f"Command queue is full ({self._max_depth} pending commands). "
                "Wait for current commands to complete or call queue_control('clear').",
                ErrorCode.QUEUE_FULL,
                data={
                    "command_name": entry.command_name,
                    "queue_depth": self._max_depth,
                },
            )

        return await entry.future

    async def stop_and_clear(self) -> dict[str, Any]:
        """Cancel all pending (not yet executing) commands and return a summary."""
        cancelled = await self._cancel_all_pending("Queue was cleared by operator.")
        return {
            "cleared_count": len(cancelled),
            "cancelled_commands": cancelled,
        }

    def status(self) -> dict[str, Any]:
        """Return current queue state for observability and the dashboard."""
        return {
            "enabled": True,
            "pending_count": self._queue.qsize(),
            "max_depth": self._max_depth,
            "rate_delay_s": self._rate_delay_s,
            "worker_running": self._worker_task is not None and not self._worker_task.done(),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _worker(self) -> None:
        last_execution_at = 0.0
        while True:
            try:
                entry = await asyncio.wait_for(self._queue.get(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            if entry.future.cancelled() or entry.future.done():
                continue

            # Pace execution to respect the rate limit window.
            elapsed = monotonic() - last_execution_at
            if elapsed < self._rate_delay_s:
                await asyncio.sleep(self._rate_delay_s - elapsed)

            try:
                result = await entry.runner()
            except Exception as exc:  # noqa: BLE001
                result = CommandResult.fail(
                    f"Unexpected error during queued execution: {exc}",
                    ErrorCode.BACKEND_ERROR,
                )

            last_execution_at = monotonic()

            if not entry.future.done():
                entry.future.set_result(result)

    async def _cancel_all_pending(self, reason: str) -> list[str]:
        cancelled: list[str] = []
        while not self._queue.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                entry = self._queue.get_nowait()
                if not entry.future.done():
                    entry.future.set_result(
                        CommandResult.fail(
                            reason,
                            ErrorCode.QUEUE_CANCELLED,
                            data={"command_name": entry.command_name},
                        )
                    )
                cancelled.append(entry.command_name)
        return cancelled
