#!/usr/bin/env python3
"""Minimal live-stack smoke checks for the HTTP MCP endpoint."""

from __future__ import annotations

import argparse
import json

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-check the live HTTP MCP server.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument(
        "--mode",
        default="connect",
        choices=("status", "connect", "flight"),
        help="Validation depth. 'flight' performs a full arm/takeoff/goto/land cycle.",
    )
    parser.add_argument("--timeout", default=60.0, type=float)
    parser.add_argument("--takeoff-altitude", default=3.0, type=float)
    parser.add_argument("--north-m", default=5.0, type=float)
    parser.add_argument("--east-m", default=0.0, type=float)
    return parser


def _dump(label: str, payload: object) -> None:
    print(f"{label}: {json.dumps(payload, sort_keys=True)}", flush=True)


async def _wait_for(session: ClientSession, description: str, predicate, timeout: float) -> dict:
    deadline = anyio.current_time() + timeout
    last_snapshot: dict | None = None

    while anyio.current_time() < deadline:
        result = await session.call_tool("get_telemetry")
        snapshot = result.structuredContent
        last_snapshot = snapshot
        if predicate(snapshot):
            _dump(description, snapshot)
            return snapshot
        await anyio.sleep(0.5)

    raise RuntimeError(f"{description} timed out. Last telemetry: {last_snapshot}")


async def _call(session: ClientSession, name: str, arguments: dict | None = None) -> dict:
    result = await session.call_tool(name, arguments or {})
    payload = result.structuredContent
    _dump(name, payload)
    return payload


async def _ensure_connected(session: ClientSession, timeout: float) -> dict:
    initial = (await session.call_tool("get_telemetry")).structuredContent
    _dump("initial_telemetry", initial)

    if initial["state"] == "fault":
        raise RuntimeError(f"Server started in fault state: {initial}")

    if initial["state"] == "disconnected":
        connect = await _call(session, "connect")
        if not connect["success"]:
            raise RuntimeError(f"connect failed: {connect}")
        await anyio.sleep(1.0)

    return await _wait_for(
        session,
        "ready_telemetry",
        lambda snapshot: snapshot["connected"] and snapshot["state"] in {"ready", "armed", "airborne"},
        timeout,
    )


async def _run_status(session: ClientSession, timeout: float) -> None:
    tools = await session.list_tools()
    _dump("tools", [tool.name for tool in tools.tools])
    await _ensure_connected(session, timeout)


async def _run_connect(session: ClientSession, timeout: float) -> None:
    ready = await _ensure_connected(session, timeout)
    _dump("connect_summary", ready)


async def _run_flight(
    session: ClientSession,
    timeout: float,
    *,
    takeoff_altitude: float,
    north_m: float,
    east_m: float,
) -> None:
    ready = await _ensure_connected(session, timeout)

    if ready["in_air"]:
        land = await _call(session, "land")
        if not land["success"]:
            raise RuntimeError(f"pre-flight land failed: {land}")
        await _wait_for(session, "preflight_landed", lambda snapshot: not snapshot["in_air"], timeout)
        ready = await _wait_for(
            session,
            "preflight_ready",
            lambda snapshot: snapshot["state"] in {"ready", "armed"},
            timeout,
        )

    if ready["state"] == "armed" and not ready["in_air"]:
        disarm = await _call(session, "disarm")
        if not disarm["success"]:
            raise RuntimeError(f"pre-flight disarm failed: {disarm}")
        await _wait_for(
            session,
            "ready_after_preflight_disarm",
            lambda snapshot: snapshot["state"] == "ready",
            timeout,
        )

    arm = await _call(session, "arm")
    if not arm["success"]:
        raise RuntimeError(f"arm failed: {arm}")
    await _wait_for(
        session,
        "armed_telemetry",
        lambda snapshot: snapshot["armed"] and snapshot["state"] in {"armed", "airborne"},
        timeout,
    )

    takeoff = await _call(session, "takeoff", {"altitude_m": takeoff_altitude})
    if not takeoff["success"]:
        raise RuntimeError(f"takeoff failed: {takeoff}")
    await _wait_for(
        session,
        "airborne_telemetry",
        lambda snapshot: snapshot["in_air"]
        and snapshot["state"] == "airborne"
        and (snapshot["relative_altitude_m"] or 0) >= max(1.5, takeoff_altitude / 2),
        timeout,
    )

    goto = await _call(
        session,
        "goto_relative",
        {"north_m": north_m, "east_m": east_m, "altitude_m": takeoff_altitude},
    )
    if not goto["success"]:
        raise RuntimeError(f"goto_relative failed: {goto}")

    hold = await _call(session, "hold")
    if not hold["success"]:
        raise RuntimeError(f"hold failed: {hold}")

    land = await _call(session, "land")
    if not land["success"]:
        raise RuntimeError(f"land failed: {land}")
    await _wait_for(session, "landed_telemetry", lambda snapshot: not snapshot["in_air"], timeout)

    current = (await session.call_tool("get_telemetry")).structuredContent
    if current["armed"]:
        disarm = await _call(session, "disarm")
        if not disarm["success"]:
            raise RuntimeError(f"disarm failed: {disarm}")
        current = await _wait_for(
            session,
            "final_ready_telemetry",
            lambda snapshot: not snapshot["armed"] and not snapshot["in_air"] and snapshot["state"] in {"ready", "connected"},
            timeout,
        )

    status = await _call(session, "get_status")
    if not status["success"]:
        raise RuntimeError(f"get_status failed: {status}")
    _dump("flight_summary", current)


async def _main(args: argparse.Namespace) -> None:
    async with streamable_http_client(args.url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            if args.mode == "status":
                await _run_status(session, args.timeout)
            elif args.mode == "connect":
                await _run_connect(session, args.timeout)
            else:
                await _run_flight(
                    session,
                    args.timeout,
                    takeoff_altitude=args.takeoff_altitude,
                    north_m=args.north_m,
                    east_m=args.east_m,
                )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    anyio.run(_main, args)


if __name__ == "__main__":
    main()
