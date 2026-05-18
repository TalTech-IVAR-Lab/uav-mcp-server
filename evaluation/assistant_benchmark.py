#!/usr/bin/env python3
"""Measure assistant plan+execute latency via the dashboard API."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluation.mcp_http import write_benchmark_artifacts

PROMPTS_SIMPLE = [
    "what is the current status of the drone?",
    "get the latest telemetry",
    "take off to 20 meters",
    "move 30 meters north at current altitude",
    "yaw 45 degrees to the right",
    "return to launch",
    "land the drone",
    "hold position",
    "what is the battery level?",
    "move 10 meters east and 5 meters up",
]

PROMPTS_COMPLEX = [
    "take off to 15 meters then move 20 meters north",
    "check the status and if ready take off to 10 meters",
    "move 25 meters east then hold position",
    "fly to 30 meters altitude and orbit at 15 meter radius",
    "get telemetry then move 10 meters south at current altitude",
    "take off to 20 meters, fly 15 meters north, then return to launch",
    "arm the drone and take off to 25 meters",
    "move 20 meters west then land",
    "check battery and if good take off to 10 meters",
    "fly 10 meters north then 10 meters east at 15 meters altitude",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark AI assistant plan+execute latency.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", default=30.0, type=float)
    parser.add_argument("--mode", choices=["simple", "complex", "both"], default="simple")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--delay", default=3.0, type=float, help="Seconds between prompts (rate limit)")
    return parser


def run_prompts(args: argparse.Namespace) -> list[dict]:
    prompts: list[str] = []
    if args.mode in ("simple", "both"):
        prompts.extend(PROMPTS_SIMPLE)
    if args.mode in ("complex", "both"):
        prompts.extend(PROMPTS_COMPLEX)

    records: list[dict] = []
    client = httpx.Client(base_url=args.base_url, timeout=args.timeout)

    for i, prompt in enumerate(prompts):
        if i > 0:
            time.sleep(args.delay)

        record: dict = {"prompt": prompt, "source": None, "proposed_commands": [], "plan_ms": 0.0, "execute_ms": 0.0, "total_ms": 0.0, "fallback": False, "assistant_text": "", "error": None}

        try:
            t0 = time.perf_counter()
            plan_resp = client.post("/dashboard/api/assistant/plan", json={"text": prompt})
            plan_ms = (time.perf_counter() - t0) * 1000.0
            plan_data = plan_resp.json()

            record["plan_ms"] = round(plan_ms, 1)
            record["source"] = plan_data.get("source", "unknown")
            record["fallback"] = plan_data.get("fallback", False)
            record["assistant_text"] = plan_data.get("assistant_text", "")
            proposed = plan_data.get("proposed_calls", [])
            record["proposed_commands"] = [c.get("tool") or c.get("command") for c in proposed]

            if proposed and plan_data.get("requires_confirmation") is False:
                t1 = time.perf_counter()
                exec_resp = client.post("/dashboard/api/assistant/execute", json={"proposed_calls": proposed})
                exec_ms = (time.perf_counter() - t1) * 1000.0
                record["execute_ms"] = round(exec_ms, 1)
            elif proposed:
                record["execute_ms"] = 0.0

            record["total_ms"] = round(record["plan_ms"] + record["execute_ms"], 1)

        except Exception as exc:
            record["error"] = str(exc)

        records.append(record)
        status = "OK" if not record["error"] else "ERR"
        cmds = ",".join(record["proposed_commands"]) or "(none)"
        print(f"  [{status}] {prompt[:50]:50s} | plan={record['plan_ms']:7.1f}ms exec={record['execute_ms']:7.1f}ms | {cmds}")

    client.close()
    return records


def main() -> None:
    args = build_parser().parse_args()
    print(f"Running assistant benchmark ({args.mode} mode)...")
    records = run_prompts(args)

    gemini_records = [r for r in records if r["source"] == "gemini" and not r["error"]]
    plan_times = [r["plan_ms"] for r in gemini_records]
    exec_times = [r["execute_ms"] for r in gemini_records if r["execute_ms"] > 0]

    summary = {
        "benchmark": "assistant_latency",
        "prompts_tested": len(records),
        "mode": args.mode,
        "gemini_plan": {
            "n": len(plan_times),
            "mean_ms": round(sum(plan_times) / len(plan_times), 1) if plan_times else 0,
            "min_ms": round(min(plan_times), 1) if plan_times else 0,
            "max_ms": round(max(plan_times), 1) if plan_times else 0,
        },
        "tool_execute": {
            "n": len(exec_times),
            "mean_ms": round(sum(exec_times) / len(exec_times), 1) if exec_times else 0,
            "min_ms": round(min(exec_times), 1) if exec_times else 0,
            "max_ms": round(max(exec_times), 1) if exec_times else 0,
        },
    }

    artifacts = write_benchmark_artifacts(
        "assistant-latency",
        records,
        summary,
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    print(json.dumps({"summary": summary, "json_path": str(artifacts.json_path)}, indent=2))


if __name__ == "__main__":
    main()
