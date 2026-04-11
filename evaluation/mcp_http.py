from __future__ import annotations

import csv
import contextlib
import json
import time
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


JsonDict = dict[str, Any]


@dataclass(slots=True)
class BenchmarkArtifacts:
    run_dir: Path
    json_path: Path
    csv_path: Path


class HttpMcpClient(AbstractAsyncContextManager["HttpMcpClient"]):
    def __init__(self, url: str) -> None:
        self.url = url
        self._exit_stack: AsyncExitStack | None = None
        self._stream_cm = None
        self._session_cm = None
        self.session: ClientSession | None = None

    async def __aenter__(self) -> "HttpMcpClient":
        stack = AsyncExitStack()

        try:
            self._stream_cm = streamable_http_client(self.url)
            read_stream, write_stream, _ = await stack.enter_async_context(self._stream_cm)
            self._session_cm = ClientSession(read_stream, write_stream)
            self.session = await stack.enter_async_context(self._session_cm)
            await self.session.initialize()
            self._exit_stack = stack
            return self
        except BaseException:
            await stack.aclose()
            self.session = None
            self._exit_stack = None
            self._session_cm = None
            self._stream_cm = None
            raise

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.__aexit__(exc_type, exc, tb)
        self.session = None
        self._exit_stack = None
        self._session_cm = None
        self._stream_cm = None

    async def call_tool(self, name: str, arguments: JsonDict | None = None) -> JsonDict:
        if self.session is None:
            raise RuntimeError("HTTP MCP client session is not initialized.")
        result = await self.session.call_tool(name, arguments or {})
        return result.structuredContent

    async def get_telemetry(self) -> JsonDict:
        return await self.call_tool("get_telemetry")

    async def get_status(self) -> JsonDict:
        return await self.call_tool("get_status")

    async def wait_for_telemetry(
        self,
        predicate: Callable[[JsonDict], bool],
        *,
        timeout_s: float,
        poll_interval_s: float = 0.5,
    ) -> JsonDict:
        deadline = anyio.current_time() + timeout_s
        last_snapshot: JsonDict | None = None

        while anyio.current_time() < deadline:
            snapshot = await self.get_telemetry()
            last_snapshot = snapshot
            if predicate(snapshot):
                return snapshot
            await anyio.sleep(poll_interval_s)

        raise RuntimeError(f"Timed out waiting for telemetry predicate. Last snapshot: {last_snapshot}")

    async def settle_action_window(self, *, window_s: float = 1.1) -> None:
        """Let the server-side action rate-limit window expire between scenarios."""
        await anyio.sleep(window_s)

    async def ensure_connected(self, *, timeout_s: float) -> JsonDict:
        snapshot = await self.get_telemetry()
        if snapshot["state"] == "fault":
            raise RuntimeError(f"Server is in fault state: {snapshot}")

        if snapshot["state"] == "disconnected":
            result = await self.call_tool("connect")
            if not result["success"]:
                raise RuntimeError(f"connect failed: {result}")

        return await self.wait_for_telemetry(
            lambda telemetry: telemetry["connected"] and telemetry["state"] in {"ready", "armed", "airborne"},
            timeout_s=timeout_s,
        )

    async def best_effort_reset_to_ready(self, *, timeout_s: float) -> JsonDict | None:
        with contextlib.suppress(Exception):
            return await self.reset_to_ready(timeout_s=timeout_s)
        return None

    async def reset_to_ready(self, *, timeout_s: float) -> JsonDict:
        snapshot = await self.ensure_connected(timeout_s=timeout_s)

        if snapshot["in_air"]:
            result = await self.call_tool("land")
            if not result["success"]:
                raise RuntimeError(f"land failed during reset: {result}")
            snapshot = await self.wait_for_telemetry(
                lambda telemetry: not telemetry["in_air"],
                timeout_s=timeout_s,
            )

        if snapshot["armed"]:
            result = await self.call_tool("disarm")
            if not result["success"]:
                raise RuntimeError(f"disarm failed during reset: {result}")

        ready_snapshot = await self.wait_for_telemetry(
            lambda telemetry: telemetry["connected"] and not telemetry["armed"] and not telemetry["in_air"] and telemetry["state"] == "ready",
            timeout_s=timeout_s,
        )
        await self.settle_action_window()
        return ready_snapshot

    async def arm_until_confirmed(
        self,
        *,
        timeout_s: float,
        max_attempts: int = 3,
    ) -> JsonDict:
        last_result: JsonDict | None = None

        for attempt in range(1, max_attempts + 1):
            result = await self.call_tool("arm")
            if result["success"]:
                await self.wait_for_telemetry(lambda telemetry: telemetry["armed"], timeout_s=timeout_s)
                return result

            last_result = result
            details = str((result.get("data") or {}).get("details", ""))
            transient_denied = result.get("error_code") == "backend_error" and "COMMAND_DENIED" in details
            if not transient_denied or attempt == max_attempts:
                raise RuntimeError(f"arm failed: {result}")

            await self.reset_to_ready(timeout_s=timeout_s)

        raise RuntimeError(f"arm failed: {last_result}")

    async def run_nominal_flight(
        self,
        *,
        timeout_s: float,
        takeoff_altitude_m: float = 3.0,
        north_m: float = 5.0,
        east_m: float = 0.0,
    ) -> JsonDict:
        await self.reset_to_ready(timeout_s=timeout_s)

        try:
            await self.arm_until_confirmed(timeout_s=timeout_s)
            await self.wait_for_telemetry(
                lambda telemetry: telemetry["armed"] and telemetry["state"] in {"armed", "airborne"},
                timeout_s=timeout_s,
            )

            takeoff = await self.call_tool("takeoff", {"altitude_m": takeoff_altitude_m})
            if not takeoff["success"]:
                raise RuntimeError(f"takeoff failed: {takeoff}")
            await self.wait_for_telemetry(
                lambda telemetry: telemetry["in_air"]
                and telemetry["state"] == "airborne"
                and (telemetry["relative_altitude_m"] or 0) >= max(1.5, takeoff_altitude_m / 2),
                timeout_s=timeout_s,
            )

            goto = await self.call_tool(
                "goto_relative",
                {"north_m": north_m, "east_m": east_m, "altitude_m": takeoff_altitude_m},
            )
            if not goto["success"]:
                raise RuntimeError(f"goto_relative failed: {goto}")

            hold = await self.call_tool("hold")
            if not hold["success"]:
                raise RuntimeError(f"hold failed: {hold}")

            land = await self.call_tool("land")
            if not land["success"]:
                raise RuntimeError(f"land failed: {land}")
            await self.wait_for_telemetry(lambda telemetry: not telemetry["in_air"], timeout_s=timeout_s)

            telemetry = await self.get_telemetry()
            if telemetry["armed"]:
                disarm = await self.call_tool("disarm")
                if not disarm["success"]:
                    raise RuntimeError(f"disarm failed: {disarm}")

            return await self.wait_for_telemetry(
                lambda telemetry: telemetry["connected"] and not telemetry["armed"] and not telemetry["in_air"] and telemetry["state"] == "ready",
                timeout_s=timeout_s,
            )
        finally:
            await self.best_effort_reset_to_ready(timeout_s=timeout_s)


def benchmark_run_dir(name: str, *, output_dir: Path | None = None) -> Path:
    base_dir = output_dir or (Path(__file__).resolve().parent / "results")
    base_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = base_dir / f"{name}-{timestamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_benchmark_artifacts(
    name: str,
    records: Sequence[JsonDict],
    summary: JsonDict,
    *,
    output_dir: Path | None = None,
) -> BenchmarkArtifacts:
    run_dir = benchmark_run_dir(name, output_dir=output_dir)
    json_path = run_dir / "results.json"
    csv_path = run_dir / "results.csv"

    json_path.write_text(
        json.dumps({"summary": summary, "records": list(records)}, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    field_names: list[str] = []
    seen_fields: set[str] = set()
    for record in records:
        for key in record:
            if key not in seen_fields:
                field_names.append(key)
                seen_fields.add(key)

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_names or ["record"])
        writer.writeheader()
        if field_names:
            writer.writerows(records)

    return BenchmarkArtifacts(run_dir=run_dir, json_path=json_path, csv_path=csv_path)


async def measure_tool_latency(client: HttpMcpClient, name: str, arguments: JsonDict | None = None) -> JsonDict:
    started_at = time.perf_counter()
    payload = await client.call_tool(name, arguments)
    latency_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
    return {
        "tool": name,
        "latency_ms": latency_ms,
        "success": payload.get("success"),
        "error_code": payload.get("error_code"),
        "message": payload.get("message"),
    }
