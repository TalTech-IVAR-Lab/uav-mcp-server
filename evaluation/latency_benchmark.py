#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from statistics import mean

import anyio

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.mcp_http import HttpMcpClient, measure_tool_latency, write_benchmark_artifacts


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


async def _measure_confirmed_arm_latency(client: HttpMcpClient, *, timeout_s: float) -> dict[str, object]:
    started_at = time.perf_counter()
    payload = await client.arm_until_confirmed(timeout_s=timeout_s)
    latency_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
    return {
        "tool": "arm",
        "latency_ms": latency_ms,
        "success": payload.get("success"),
        "error_code": payload.get("error_code"),
        "message": payload.get("message"),
    }


async def _measure_confirmed_disarm_latency(client: HttpMcpClient, *, timeout_s: float) -> dict[str, object]:
    started_at = time.perf_counter()
    payload = await client.call_tool("disarm")
    if not payload["success"]:
        raise RuntimeError(f"disarm failed: {payload}")
    await client.wait_for_telemetry(
        lambda telemetry: telemetry["state"] == "ready" and not telemetry["armed"],
        timeout_s=timeout_s,
    )
    latency_ms = round((time.perf_counter() - started_at) * 1000.0, 3)
    return {
        "tool": "disarm",
        "latency_ms": latency_ms,
        "success": payload.get("success"),
        "error_code": payload.get("error_code"),
        "message": payload.get("message"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure MCP tool latency against the live HTTP endpoint.")
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp")
    parser.add_argument("--iterations", default=10, type=_positive_int)
    parser.add_argument("--timeout", default=60.0, type=float)
    parser.add_argument("--output-dir", default=None)
    return parser


async def run(args: argparse.Namespace) -> None:
    records: list[dict[str, object]] = []

    async with HttpMcpClient(args.url) as client:
        for iteration in range(1, args.iterations + 1):
            await client.reset_to_ready(timeout_s=args.timeout)
            try:
                status_record = await measure_tool_latency(client, "get_status")
                status_record["iteration"] = iteration
                records.append(status_record)

                telemetry_record = await measure_tool_latency(client, "get_telemetry")
                telemetry_record["iteration"] = iteration
                records.append(telemetry_record)

                arm_record = await _measure_confirmed_arm_latency(client, timeout_s=args.timeout)
                arm_record["iteration"] = iteration
                records.append(arm_record)

                disarm_record = await _measure_confirmed_disarm_latency(client, timeout_s=args.timeout)
                disarm_record["iteration"] = iteration
                records.append(disarm_record)
            finally:
                await client.best_effort_reset_to_ready(timeout_s=args.timeout)

    latencies = [float(record["latency_ms"]) for record in records]
    summary = {
        "benchmark": "latency",
        "iterations": args.iterations,
        "sample_count": len(records),
        "mean_latency_ms": round(mean(latencies), 3),
        "max_latency_ms": round(max(latencies), 3),
        "min_latency_ms": round(min(latencies), 3),
    }
    artifacts = write_benchmark_artifacts(
        "latency",
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
