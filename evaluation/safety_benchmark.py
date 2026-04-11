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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exercise live MCP safety rejections against PX4 SITL.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--timeout", default=90.0, type=float)
    parser.add_argument("--takeoff-altitude", default=3.0, type=float)
    parser.add_argument("--geofence-north-m", default=100.0, type=float)
    parser.add_argument("--output-dir", default=None)
    return parser


async def run(args: argparse.Namespace) -> None:
    records: list[dict[str, object]] = []

    async with HttpMcpClient(args.url) as client:
        await client.reset_to_ready(timeout_s=args.timeout)

        try:
            wrong_state = await client.call_tool("takeoff", {"altitude_m": args.takeoff_altitude})
            records.append(
                {
                    "scenario": "takeoff_from_ready",
                    "success": wrong_state["success"],
                    "error_code": wrong_state["error_code"],
                    "message": wrong_state["message"],
                    "expected_error_code": "wrong_state",
                    "passed": wrong_state["success"] is False and wrong_state["error_code"] == "wrong_state",
                }
            )

            arm = await client.arm_until_confirmed(timeout_s=args.timeout)
            if not arm["success"]:
                raise RuntimeError(f"arm failed before geofence check: {arm}")

            takeoff = await client.call_tool("takeoff", {"altitude_m": args.takeoff_altitude})
            if not takeoff["success"]:
                raise RuntimeError(f"takeoff failed before geofence check: {takeoff}")
            await client.wait_for_telemetry(lambda telemetry: telemetry["in_air"], timeout_s=args.timeout)

            geofence = await client.call_tool(
                "goto_relative",
                {
                    "north_m": args.geofence_north_m,
                    "east_m": 0.0,
                    "altitude_m": args.takeoff_altitude,
                },
            )
            records.append(
                {
                    "scenario": "geofence_violation",
                    "success": geofence["success"],
                    "error_code": geofence["error_code"],
                    "message": geofence["message"],
                    "expected_error_code": "geofence_violation",
                    "passed": geofence["success"] is False and geofence["error_code"] == "geofence_violation",
                }
            )
        finally:
            await client.best_effort_reset_to_ready(timeout_s=args.timeout)

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
