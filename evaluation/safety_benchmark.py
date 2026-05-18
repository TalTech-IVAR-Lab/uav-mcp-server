#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import anyio

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.mcp_http import HttpMcpClient, write_benchmark_artifacts


def _error_payload(exc: BaseException) -> dict[str, str]:
    root = exc
    while isinstance(root, BaseExceptionGroup) and root.exceptions:
        root = root.exceptions[0]
    return {"error": type(root).__name__, "message": str(root)}


def _record(scenario: str, result: dict, expected: str) -> dict[str, object]:
    return {
        "scenario": scenario,
        "success": result["success"],
        "error_code": result.get("error_code"),
        "message": result.get("message", ""),
        "expected_error_code": expected,
        "passed": result["success"] is False and result.get("error_code") == expected,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exercise live MCP safety rejections against PX4 SITL.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--timeout", default=90.0, type=float)
    parser.add_argument("--takeoff-altitude", default=3.0, type=float)
    parser.add_argument("--geofence-north-m", default=100.0, type=float)
    parser.add_argument("--output-dir", default=None)
    return parser


async def _get_airborne(client: HttpMcpClient, *, timeout_s: float, alt: float) -> None:
    await client.reset_to_ready(timeout_s=timeout_s)
    await client.settle_action_window()
    await client.arm_until_confirmed(timeout_s=timeout_s)
    takeoff = await client.call_tool("takeoff", {"altitude_m": alt})
    if not takeoff["success"]:
        raise RuntimeError(f"takeoff failed during setup: {takeoff}")
    await client.wait_for_telemetry(lambda t: t["in_air"], timeout_s=timeout_s)


async def run(args: argparse.Namespace) -> None:
    records: list[dict[str, object]] = []
    timeout = args.timeout
    alt = args.takeoff_altitude

    async with HttpMcpClient(args.url) as client:

        # === Ground-state scenarios (no flight needed) ===

        # 1. takeoff from READY (not armed) → wrong_state
        await client.reset_to_ready(timeout_s=timeout)
        result = await client.call_tool("takeoff", {"altitude_m": alt})
        records.append(_record("takeoff_from_ready", result, "wrong_state"))

        # 2. disarm from READY → wrong_state
        await client.settle_action_window()
        result = await client.call_tool("disarm")
        records.append(_record("disarm_from_ready", result, "wrong_state"))

        # 3. goto_relative from READY → wrong_state
        await client.settle_action_window()
        result = await client.call_tool(
            "goto_relative", {"north_m": 5.0, "east_m": 0.0, "altitude_m": 5.0}
        )
        records.append(_record("goto_relative_from_ready", result, "wrong_state"))

        # 4. orbit from READY → wrong_state
        await client.settle_action_window()
        result = await client.call_tool(
            "orbit",
            {
                "latitude_deg": 48.14767,
                "longitude_deg": 11.56960,
                "absolute_altitude_m": 425.0,
                "radius_m": 10.0,
                "velocity_m_s": 3.0,
            },
        )
        records.append(_record("orbit_from_ready", result, "wrong_state"))

        # === Armed-state scenarios ===

        # 5. takeoff altitude too low (0.5 m < min 2.0 m) → invalid_params
        await client.reset_to_ready(timeout_s=timeout)
        await client.settle_action_window()
        await client.arm_until_confirmed(timeout_s=timeout)
        result = await client.call_tool("takeoff", {"altitude_m": 0.5})
        records.append(_record("takeoff_altitude_too_low", result, "invalid_params"))

        # 6. takeoff altitude too high (999 m > max 120 m) → invalid_params
        await client.settle_action_window()
        result = await client.call_tool("takeoff", {"altitude_m": 999.0})
        records.append(_record("takeoff_altitude_too_high", result, "invalid_params"))

        # Reset before airborne scenarios
        await client.best_effort_reset_to_ready(timeout_s=timeout)

        # === Airborne-state scenarios ===

        # 7. geofence violation via goto_relative → geofence_violation
        await _get_airborne(client, timeout_s=timeout, alt=alt)
        await client.settle_action_window()
        result = await client.call_tool(
            "goto_relative",
            {"north_m": args.geofence_north_m, "east_m": 0.0, "altitude_m": alt},
        )
        records.append(_record("geofence_goto_relative", result, "geofence_violation"))

        # 8. goto_relative distance exceeds max (200 m > 150 m limit) → invalid_params
        await client.settle_action_window()
        result = await client.call_tool(
            "goto_relative", {"north_m": 200.0, "east_m": 0.0, "altitude_m": 3.0}
        )
        records.append(_record("goto_relative_distance_exceeded", result, "invalid_params"))

        # 9. orbit radius too small (1 m < min 5 m) → invalid_params
        await client.settle_action_window()
        telem = await client.get_telemetry()
        result = await client.call_tool(
            "orbit",
            {
                "latitude_deg": telem["latitude_deg"],
                "longitude_deg": telem["longitude_deg"],
                "absolute_altitude_m": telem.get("absolute_altitude_m", 425.0),
                "radius_m": 1.0,
                "velocity_m_s": 3.0,
            },
        )
        records.append(_record("orbit_radius_too_small", result, "invalid_params"))

        # 10. orbit velocity too high (50 m/s > max 15 m/s) → invalid_params
        await client.settle_action_window()
        result = await client.call_tool(
            "orbit",
            {
                "latitude_deg": telem["latitude_deg"],
                "longitude_deg": telem["longitude_deg"],
                "absolute_altitude_m": telem.get("absolute_altitude_m", 425.0),
                "radius_m": 10.0,
                "velocity_m_s": 50.0,
            },
        )
        records.append(_record("orbit_velocity_too_high", result, "invalid_params"))

        # Clean up
        await client.best_effort_reset_to_ready(timeout_s=timeout)

    passed = sum(1 for record in records if record["passed"])
    summary = {
        "benchmark": "safety",
        "scenario_count": len(records),
        "passed_scenarios": passed,
        "passed": passed == len(records),
    }
    artifacts = write_benchmark_artifacts(
        "safety",
        records,
        summary,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    print(json.dumps({"summary": summary, "json_path": str(artifacts.json_path), "csv_path": str(artifacts.csv_path)}, indent=2))


def main() -> None:
    args = build_parser().parse_args()
    try:
        anyio.run(run, args)
    except BaseException as exc:
        print(json.dumps(_error_payload(exc), indent=2), file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
