#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import anyio

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.mcp_http import HttpMcpClient, write_benchmark_artifacts


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("iterations must be >= 1")
    return parsed


def _error_payload(exc: BaseException) -> dict[str, str]:
    root = exc
    while isinstance(root, BaseExceptionGroup) and root.exceptions:
        root = root.exceptions[0]
    return {"error": type(root).__name__, "message": str(root)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run repeated live MCP reliability checks.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--iterations", default=3, type=_positive_int)
    parser.add_argument("--timeout", default=90.0, type=float)
    parser.add_argument("--takeoff-altitude", default=3.0, type=float)
    parser.add_argument("--north-m", default=5.0, type=float)
    parser.add_argument("--east-m", default=0.0, type=float)
    parser.add_argument("--output-dir", default=None)
    return parser


async def run(args: argparse.Namespace) -> None:
    records: list[dict[str, object]] = []

    for iteration in range(1, args.iterations + 1):
        started_at = time.perf_counter()
        record: dict[str, object] = {"iteration": iteration}
        try:
            async with HttpMcpClient(args.url) as client:
                final_snapshot = await client.run_nominal_flight(
                    timeout_s=args.timeout,
                    takeoff_altitude_m=args.takeoff_altitude,
                    north_m=args.north_m,
                    east_m=args.east_m,
                )
            record.update(
                {
                    "success": True,
                    "duration_s": round(time.perf_counter() - started_at, 3),
                    "final_state": final_snapshot["state"],
                    "final_armed": final_snapshot["armed"],
                    "final_in_air": final_snapshot["in_air"],
                }
            )
        except Exception as exc:  # pragma: no cover - exercised in live runs
            record.update(
                {
                    "success": False,
                    "duration_s": round(time.perf_counter() - started_at, 3),
                    "error": str(exc),
                }
            )
        records.append(record)

    successes = sum(1 for record in records if record["success"])
    summary = {
        "benchmark": "reliability",
        "iterations": args.iterations,
        "successful_iterations": successes,
        "success_rate": round(successes / args.iterations, 3),
        "pass_threshold": 1.0,
        "passed": successes == args.iterations,
    }
    artifacts = write_benchmark_artifacts(
        "reliability",
        records,
        summary,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    if successes == 0:
        raise RuntimeError(
            f"reliability benchmark did not complete any successful iteration; see {artifacts.json_path}"
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
