"""Observability data model for thesis-facing analysis.

The module intentionally stays dependency-free. It reads reproducible
benchmark artifacts from ``evaluation/results`` and records live operational
events into a small SQLite database under ``.run``.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from typing import Any

UTC = timezone.utc
BENCHMARK_NAMES = ("latency", "reliability", "safety")
OBSERVABILITY_DB_NAME = "observability.sqlite3"
MIN_LATENCY_SAMPLES = 30
MIN_RELIABILITY_ITERATIONS = 5
MIN_SAFETY_SCENARIOS = 5


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat(timespec="milliseconds")


def percentile(values: Iterable[float], percentile_value: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(ordered[0], 3)

    rank = (len(ordered) - 1) * percentile_value / 100.0
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    weight = rank - lower
    return round(ordered[lower] * (1.0 - weight) + ordered[upper] * weight, 3)


def _parse_run_timestamp(run_name: str, path: Path) -> str | None:
    raw_value = run_name.rsplit("-", 1)[-1]
    try:
        return datetime.strptime(raw_value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).isoformat(timespec="seconds")
    except ValueError:
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")
        return None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _metadata_env(run: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(run, dict):
        return {}
    metadata = run.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    environment = metadata.get("environment")
    return environment if isinstance(environment, dict) else {}


def _metadata_git(run: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(run, dict):
        return {}
    metadata = run.get("metadata")
    if not isinstance(metadata, dict):
        return {}
    git = metadata.get("git")
    return git if isinstance(git, dict) else {}


def _source_run(run: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(run, dict):
        return None
    env = _metadata_env(run)
    git = _metadata_git(run)
    return {
        "run_id": run.get("run_id"),
        "timestamp": run.get("timestamp"),
        "json_path": run.get("json_path"),
        "csv_path": run.get("csv_path"),
        "backend_mode": env.get("backend_mode"),
        "git_commit": git.get("commit"),
        "git_branch": git.get("branch"),
        "git_dirty": git.get("dirty"),
    }


def _warning(code: str, message: str, *, severity: str = "warning") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("artifact root must be a JSON object")
    return payload


@dataclass(slots=True)
class ObservabilityEvent:
    timestamp: str
    source: str
    action: str
    command: str | None = None
    success: bool | None = None
    error_code: str | None = None
    duration_ms: float | None = None
    message: str | None = None
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    telemetry_before: dict[str, Any] | None = None
    telemetry_after: dict[str, Any] | None = None
    correlation_id: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "source": self.source,
            "action": self.action,
            "command": self.command,
            "success": self.success,
            "error_code": self.error_code,
            "duration_ms": self.duration_ms,
            "message": self.message,
            "request": self.request,
            "response": self.response,
            "telemetry_before": self.telemetry_before,
            "telemetry_after": self.telemetry_after,
            "correlation_id": self.correlation_id,
        }


class ObservabilityStore:
    """SQLite-backed event store for runtime observability."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observability_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    source TEXT NOT NULL,
                    action TEXT NOT NULL,
                    command TEXT,
                    success INTEGER,
                    error_code TEXT,
                    duration_ms REAL,
                    message TEXT,
                    request_json TEXT,
                    response_json TEXT,
                    telemetry_before_json TEXT,
                    telemetry_after_json TEXT,
                    correlation_id TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_observability_events_timestamp "
                "ON observability_events(timestamp DESC)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_observability_events_command "
                "ON observability_events(command)"
            )

    def record(self, event: ObservabilityEvent) -> str:
        correlation_id = event.correlation_id or str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO observability_events (
                    timestamp, source, action, command, success, error_code, duration_ms,
                    message, request_json, response_json, telemetry_before_json,
                    telemetry_after_json, correlation_id
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.timestamp,
                    event.source,
                    event.action,
                    event.command,
                    None if event.success is None else int(event.success),
                    event.error_code,
                    event.duration_ms,
                    event.message,
                    _json_or_none(event.request),
                    _json_or_none(event.response),
                    _json_or_none(event.telemetry_before),
                    _json_or_none(event.telemetry_after),
                    correlation_id,
                ),
            )
        return correlation_id

    def recent(self, *, limit: int = 200) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 1000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM observability_events
                ORDER BY timestamp DESC, id DESC
                LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def summary(self, minutes: int = 10, bucket_size_s: int = 2) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        # minutes=0 means all-time (no time filter).
        if minutes > 0:
            start_time = now - timedelta(minutes=minutes)
            # Scope ALL stats — counts, latencies, timeseries — to the selected
            # time window so the graphs and KPIs reflect the same period.
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM observability_events WHERE timestamp >= ? ORDER BY timestamp ASC",
                    (start_time.isoformat(),),
                ).fetchall()
        else:
            start_time = now - timedelta(minutes=60)  # timeseries still needs a range
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT * FROM observability_events ORDER BY timestamp ASC"
                ).fetchall()

        events = [self._row_to_dict(row) for row in rows]
        
        command_events = [e for e in events if e.get("action") == "command"]
        plan_events = [e for e in events if e.get("action") == "plan" and e.get("source") == "assistant"]
        
        by_command = Counter(str(event.get("command") or "unknown") for event in command_events)
        by_error = Counter(str(event.get("error_code") or "none") for event in command_events)
        
        latencies_by_command: dict[str, list[float]] = defaultdict(list)
        for event in command_events:
            cmd = str(event.get("command") or "unknown")
            if isinstance(event.get("duration_ms"), (int, float)):
                latencies_by_command[cmd].append(float(event["duration_ms"]))
                
        by_command_latency = {
            cmd: latency_stats(lats)
            for cmd, lats in latencies_by_command.items()
        }
        
        safety_rejections = [
            event
            for event in command_events
            if event.get("success") is False and event.get("error_code") not in {None, "none"}
        ]
        latencies = [
            float(event["duration_ms"])
            for event in command_events
            if isinstance(event.get("duration_ms"), (int, float))
        ]
        
        plan_latencies = [
            float(event["duration_ms"])
            for event in plan_events
            if isinstance(event.get("duration_ms"), (int, float))
        ]
        plan_success_count = sum(1 for event in plan_events if event.get("success") is True)
        plan_success_rate = plan_success_count / len(plan_events) if plan_events else None
        
        # Calculate Timeseries (reuse already-computed now/start_time above)
        start_ts = start_time.timestamp()
        
        buckets_data: dict[int, list[dict[str, Any]]] = {}
        for e in events:
            if not e.get("timestamp"):
                continue
            try:
                dt = datetime.fromisoformat(e["timestamp"])
                ts = dt.timestamp()
                if ts < start_ts:
                    continue
                bucket_idx = int((ts - start_ts) // bucket_size_s)
                if bucket_idx not in buckets_data:
                    buckets_data[bucket_idx] = []
                buckets_data[bucket_idx].append(e)
            except Exception:
                pass
                
        timestamps = []
        throughputSuccess = []
        throughputError = []
        throughputManualSuccess = []
        throughputManualError = []
        latencyP95 = []
        latencyMean = []
        
        num_buckets = int((now.timestamp() - start_ts) // bucket_size_s) + 1
        for i in range(num_buckets):
            b_time = start_time + timedelta(seconds=i * bucket_size_s)
            timestamps.append(b_time.isoformat())
            
            b_events = buckets_data.get(i, [])
            success_count = sum(1 for e in b_events if e.get("action") == "command" and e.get("source") != "manual" and e.get("success") is True)
            error_count = sum(1 for e in b_events if e.get("action") == "command" and e.get("source") != "manual" and e.get("success") is False)
            
            throughputSuccess.append(success_count)
            throughputError.append(error_count)

            manual_success_count = sum(1 for e in b_events if e.get("action") == "command" and e.get("source") == "manual" and e.get("success") is True)
            manual_error_count = sum(1 for e in b_events if e.get("action") == "command" and e.get("source") == "manual" and e.get("success") is False)

            throughputManualSuccess.append(manual_success_count)
            throughputManualError.append(manual_error_count)

            lats = [float(e["duration_ms"]) for e in b_events if e.get("action") == "command" and isinstance(e.get("duration_ms"), (int, float))]
            if lats:
                stats = latency_stats(lats)
                latencyP95.append(stats["p95"] or 0)
                latencyMean.append(stats["mean"] or 0)
            else:
                latencyP95.append(0)
                latencyMean.append(0)

        timeseries = {
            "timestamps": timestamps,
            "throughputSuccess": throughputSuccess,
            "throughputError": throughputError,
            "throughputManualSuccess": throughputManualSuccess,
            "throughputManualError": throughputManualError,
            "latencyP95": latencyP95,
            "latencyMean": latencyMean,
        }
        
        return {
            "event_count": len(events),
            "command_count": len(command_events),
            "safety_rejection_count": len(safety_rejections),
            "by_command": dict(by_command),
            "by_command_latency": by_command_latency,
            "by_error_code": dict(by_error),
            "latency_ms": latency_stats(latencies),
            "assistant_metrics": {
                "latency_ms": latency_stats(plan_latencies),
                "success_rate": plan_success_rate,
                "plan_count": len(plan_events),
            },
            "latest_event": events[-1] if events else None,
            "timeseries": timeseries,
        }

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        def parse_json(field_name: str) -> Any:
            raw_value = row[field_name]
            if raw_value is None:
                return None
            try:
                return json.loads(raw_value)
            except json.JSONDecodeError:
                return None

        return {
            "id": row["id"],
            "timestamp": row["timestamp"],
            "source": row["source"],
            "action": row["action"],
            "command": row["command"],
            "success": None if row["success"] is None else bool(row["success"]),
            "error_code": row["error_code"],
            "duration_ms": row["duration_ms"],
            "message": row["message"],
            "request": parse_json("request_json"),
            "response": parse_json("response_json"),
            "telemetry_before": parse_json("telemetry_before_json"),
            "telemetry_after": parse_json("telemetry_after_json"),
            "correlation_id": row["correlation_id"],
        }


def latency_stats(values: Iterable[float]) -> dict[str, float | int | None]:
    numeric = [float(value) for value in values]
    return {
        "count": len(numeric),
        "min": round(min(numeric), 3) if numeric else None,
        "mean": round(mean(numeric), 3) if numeric else None,
        "p50": percentile(numeric, 50),
        "p95": percentile(numeric, 95),
        "p99": percentile(numeric, 99),
        "max": round(max(numeric), 3) if numeric else None,
    }


class ObservabilityService:
    """Read benchmark artifacts and combine them with runtime observations."""

    def __init__(self, repo_root: Path, *, store: ObservabilityStore | None = None) -> None:
        self.repo_root = repo_root
        self.results_dir = repo_root / "evaluation" / "results"
        self.store = store or ObservabilityStore(repo_root / ".run" / OBSERVABILITY_DB_NAME)

    def record_event(self, event: ObservabilityEvent) -> str:
        return self.store.record(event)

    def list_runs(self) -> dict[str, Any]:
        runs, errors = self._load_runs()
        return {
            "results_dir": str(self.results_dir),
            "results_dir_exists": self.results_dir.exists(),
            "run_count": len(runs),
            "runs": runs,
            "load_errors": errors,
        }

    def run_detail(self, run_id: str) -> dict[str, Any]:
        run_name = Path(run_id).name
        if run_name != run_id or not run_name:
            raise ValueError("Invalid run id.")
        json_path = self.results_dir / run_name / "results.json"
        if not json_path.exists():
            raise FileNotFoundError(run_id)

        payload = _load_json(json_path)
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        records = payload.get("records") if isinstance(payload.get("records"), list) else []
        return {
            "run_id": run_name,
            "json_path": str(json_path),
            "csv_path": str(json_path.with_name("results.csv")),
            "timestamp": _parse_run_timestamp(run_name, json_path),
            "benchmark": str(summary.get("benchmark") or run_name.split("-", 1)[0]).lower(),
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
            "summary": summary,
            "records": records,
            "derived": derive_benchmark_metrics(str(summary.get("benchmark") or ""), records, summary),
        }

    def recent_events(self, *, limit: int = 200) -> list[dict[str, Any]]:
        return self.store.recent(limit=limit)

    def summary(
        self,
        *,
        runtime_health: dict[str, Any] | None = None,
        minutes: int = 10,
        bucket_size_s: int = 2,
    ) -> dict[str, Any]:
        runs, errors = self._load_runs()
        latest_by_benchmark: dict[str, dict[str, Any]] = {}
        for run in runs:
            benchmark = str(run.get("benchmark") or "").lower()
            current = latest_by_benchmark.get(benchmark)
            if current is None or str(run.get("timestamp") or "") > str(current.get("timestamp") or ""):
                latest_by_benchmark[benchmark] = run

        benchmark_status = {name: latest_by_benchmark.get(name) for name in BENCHMARK_NAMES}
        complete_suite = all(benchmark_status[name] is not None for name in BENCHMARK_NAMES)
        reliability_passed = (benchmark_status.get("reliability") or {}).get("passed")
        safety_passed = (benchmark_status.get("safety") or {}).get("passed")
        ready_for_thesis = complete_suite and reliability_passed is True and safety_passed is True
        thesis_metrics = derive_thesis_metrics(
            benchmark_status,
            runtime_health=runtime_health or {},
            load_errors=errors,
        )
        return {
            "timestamp": now_iso(),
            "results_dir": str(self.results_dir),
            "run_count": len(runs),
            "benchmarks": benchmark_status,
            "latest_run": runs[0] if runs else None,
            "readiness": {
                "complete_suite": complete_suite,
                "ready_for_thesis": ready_for_thesis,
                "has_latency": benchmark_status["latency"] is not None,
                "has_reliability": benchmark_status["reliability"] is not None,
                "has_safety": benchmark_status["safety"] is not None,
                "reliability_passed": reliability_passed,
                "safety_passed": safety_passed,
                "evidence_ready": thesis_metrics["validity"]["is_valid_evidence"],
                "warning_count": len(thesis_metrics["validity"]["warnings"]),
            },
            "thesis_metrics": thesis_metrics,
            "runtime": runtime_health or {},
            "events": self.store.summary(minutes=minutes, bucket_size_s=bucket_size_s),
            "load_errors": errors,
        }

    def export(self) -> dict[str, Any]:
        runs, errors = self._load_runs()
        summary = self.summary()
        return {
            "generated_at": now_iso(),
            "summary": summary,
            "thesis_metrics": summary.get("thesis_metrics", {}),
            "runs": runs,
            "events": self.store.recent(limit=1000),
            "load_errors": errors,
        }

    def _load_runs(self) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        runs: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        if not self.results_dir.exists():
            return runs, errors

        for json_path in sorted(self.results_dir.glob("*/results.json")):
            try:
                payload = _load_json(json_path)
                run = summarize_artifact(json_path, payload)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                errors.append({"path": str(json_path), "message": str(exc)})
                continue
            runs.append(run)

        runs.sort(key=lambda entry: str(entry.get("timestamp") or ""), reverse=True)
        return runs, errors


def summarize_artifact(json_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("results.json is missing a summary object")

    records = payload.get("records")
    if not isinstance(records, list):
        records = []

    run_id = json_path.parent.name
    benchmark = str(summary.get("benchmark") or run_id.split("-", 1)[0]).lower()
    derived = derive_benchmark_metrics(benchmark, records, summary)
    return {
        "run_id": run_id,
        "benchmark": benchmark,
        "timestamp": _parse_run_timestamp(run_id, json_path),
        "json_path": str(json_path),
        "csv_path": str(json_path.parent / "results.csv"),
        "record_count": len(records),
        "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        "summary": summary,
        "passed": summary.get("passed") if isinstance(summary.get("passed"), bool) else None,
        "headline": benchmark_headline(benchmark, summary, derived, record_count=len(records)),
        "derived": derived,
    }


def derive_benchmark_metrics(
    benchmark: str,
    records: list[Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    if benchmark == "latency":
        return derive_latency_metrics(records)
    if benchmark == "reliability":
        return derive_reliability_metrics(records, summary)
    if benchmark == "safety":
        return derive_safety_metrics(records, summary)
    return {"record_count": len(records)}


def derive_latency_metrics(records: list[Any]) -> dict[str, Any]:
    by_tool: dict[str, list[float]] = defaultdict(list)
    all_latencies: list[float] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        latency_ms = _safe_float(record.get("latency_ms"))
        tool = str(record.get("tool") or "unknown")
        if latency_ms is None:
            continue
        by_tool[tool].append(latency_ms)
        all_latencies.append(latency_ms)

    return {
        "latency_ms": latency_stats(all_latencies),
        "by_tool": {tool: latency_stats(values) for tool, values in sorted(by_tool.items())},
        "slowest_samples": sorted(
            [record for record in records if isinstance(record, dict) and _safe_float(record.get("latency_ms")) is not None],
            key=lambda record: float(record["latency_ms"]),
            reverse=True,
        )[:10],
    }


def derive_reliability_metrics(records: list[Any], summary: dict[str, Any]) -> dict[str, Any]:
    durations = [
        value
        for record in records
        if isinstance(record, dict)
        for value in [_safe_float(record.get("duration_s"))]
        if value is not None
    ]
    failures = [record for record in records if isinstance(record, dict) and record.get("success") is False]
    return {
        "success_rate": _safe_float(summary.get("success_rate")),
        "duration_s": latency_stats(durations),
        "failure_count": len(failures),
        "failures": failures[:10],
    }


def derive_safety_metrics(records: list[Any], summary: dict[str, Any]) -> dict[str, Any]:
    by_error = Counter(
        str(record.get("error_code") or "none")
        for record in records
        if isinstance(record, dict)
    )
    classifications = [_classify_safety_record(record) for record in records if isinstance(record, dict)]
    by_scenario = {
        str(record.get("scenario") or "unknown"): {
            "passed": record.get("passed"),
            "error_code": record.get("error_code"),
            "expected_error_code": record.get("expected_error_code"),
            "message": record.get("message"),
            "classification": _classify_safety_record(record),
        }
        for record in records
        if isinstance(record, dict)
    }
    scenario_count = summary.get("scenario_count")
    passed_scenarios = summary.get("passed_scenarios")
    pass_rate = None
    if isinstance(scenario_count, int) and scenario_count > 0 and isinstance(passed_scenarios, int):
        pass_rate = round(passed_scenarios / scenario_count, 3)
    return {
        "pass_rate": pass_rate,
        "by_error_code": dict(by_error),
        "by_scenario": by_scenario,
        "false_accept_count": classifications.count("false_accept"),
        "false_reject_count": classifications.count("false_reject"),
        "wrong_error_code_count": classifications.count("wrong_error_code"),
    }


def _classify_safety_record(record: dict[str, Any]) -> str:
    expected = record.get("expected_error_code")
    expected_code = None if expected in {None, "", "none"} else str(expected)
    actual = record.get("error_code")
    actual_code = None if actual in {None, "", "none"} else str(actual)
    success = record.get("success")

    if expected_code is None:
        if success is False:
            return "false_reject"
        return "correct_accept"
    if success is True:
        return "false_accept"
    if actual_code != expected_code:
        return "wrong_error_code"
    return "correct_rejection"


def derive_thesis_metrics(
    benchmark_status: dict[str, dict[str, Any] | None],
    *,
    runtime_health: dict[str, Any],
    load_errors: list[dict[str, str]],
) -> dict[str, Any]:
    latency_run = benchmark_status.get("latency")
    reliability_run = benchmark_status.get("reliability")
    safety_run = benchmark_status.get("safety")

    latency = _derive_thesis_latency(latency_run)
    reliability = _derive_thesis_reliability(reliability_run)
    safety = _derive_thesis_safety(safety_run)
    validity = derive_evidence_validity(
        benchmark_status,
        runtime_health=runtime_health,
        load_errors=load_errors,
        latency=latency,
        reliability=reliability,
        safety=safety,
    )

    return {
        "generated_at": now_iso(),
        "validity": validity,
        "latency": latency,
        "reliability": reliability,
        "safety": safety,
        "tables": {
            "latency_by_tool": latency["by_tool_rows"],
            "reliability_summary": reliability["summary_rows"],
            "safety_scenarios": safety["scenario_rows"],
            "thesis_numbers": _thesis_number_rows(latency, reliability, safety),
        },
    }


def _derive_thesis_latency(run: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(run, dict):
        return {
            "available": False,
            "source_run": None,
            "latency_ms": latency_stats([]),
            "by_tool_rows": [],
            "confirmed_action_latency_ms": latency_stats([]),
        }

    derived = run.get("derived") if isinstance(run.get("derived"), dict) else {}
    latency_ms = derived.get("latency_ms") if isinstance(derived.get("latency_ms"), dict) else latency_stats([])
    by_tool = derived.get("by_tool") if isinstance(derived.get("by_tool"), dict) else {}
    by_tool_rows = [
        {
            "tool": tool,
            "n": stats.get("count"),
            "mean_ms": stats.get("mean"),
            "p50_ms": stats.get("p50"),
            "p95_ms": stats.get("p95"),
            "p99_ms": stats.get("p99"),
            "min_ms": stats.get("min"),
            "max_ms": stats.get("max"),
        }
        for tool, stats in sorted(by_tool.items())
        if isinstance(stats, dict)
    ]

    confirmed_values = [
        latency_ms
        for record in _load_run_records(run)
        if record.get("tool") in {"arm", "disarm"}
        for latency_ms in [_safe_float(record.get("latency_ms"))]
        if latency_ms is not None
    ]

    return {
        "available": True,
        "source_run": _source_run(run),
        "sample_count": latency_ms.get("count"),
        "latency_ms": latency_ms,
        "by_tool_rows": by_tool_rows,
        "confirmed_action_latency_ms": latency_stats(confirmed_values),
        "slowest_samples": derived.get("slowest_samples", []),
    }


def _derive_thesis_reliability(run: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(run, dict):
        return {
            "available": False,
            "source_run": None,
            "iterations": None,
            "success_rate": None,
            "recovery_to_ready_rate": None,
            "duration_s": latency_stats([]),
            "summary_rows": [],
            "failure_categories": {},
        }

    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    derived = run.get("derived") if isinstance(run.get("derived"), dict) else {}
    records = _load_run_records(run)
    iterations = _safe_int(summary.get("iterations"))
    ready_count = sum(
        1
        for record in records
        if record.get("final_state") == "ready"
        and record.get("final_armed") is False
        and record.get("final_in_air") is False
    )
    recovery_rate = round(ready_count / len(records), 3) if records else None
    failures = [record for record in records if record.get("success") is False]
    failure_categories = Counter(str(record.get("error") or "unknown") for record in failures)
    duration_s = derived.get("duration_s") if isinstance(derived.get("duration_s"), dict) else latency_stats([])
    success_rate = _safe_float(derived.get("success_rate"))

    return {
        "available": True,
        "source_run": _source_run(run),
        "iterations": iterations,
        "successful_iterations": _safe_int(summary.get("successful_iterations")),
        "success_rate": success_rate,
        "recovery_to_ready_rate": recovery_rate,
        "duration_s": duration_s,
        "failure_count": len(failures),
        "failure_categories": dict(failure_categories),
        "summary_rows": [
            {"metric": "Nominal mission success rate", "value": success_rate, "unit": "ratio"},
            {"metric": "Recovery to ready rate", "value": recovery_rate, "unit": "ratio"},
            {"metric": "Mean run duration", "value": duration_s.get("mean"), "unit": "s"},
            {"metric": "P95 run duration", "value": duration_s.get("p95"), "unit": "s"},
        ],
    }


def _derive_thesis_safety(run: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(run, dict):
        return {
            "available": False,
            "source_run": None,
            "scenario_count": None,
            "pass_rate": None,
            "scenario_rows": [],
            "false_accept_count": 0,
            "false_reject_count": 0,
            "wrong_error_code_count": 0,
        }

    summary = run.get("summary") if isinstance(run.get("summary"), dict) else {}
    derived = run.get("derived") if isinstance(run.get("derived"), dict) else {}
    records = _load_run_records(run)
    scenario_rows = [
        {
            "scenario": str(record.get("scenario") or "unknown"),
            "expected_error_code": record.get("expected_error_code"),
            "actual_error_code": record.get("error_code"),
            "passed": record.get("passed"),
            "classification": _classify_safety_record(record),
            "message": record.get("message"),
        }
        for record in records
    ]

    return {
        "available": True,
        "source_run": _source_run(run),
        "scenario_count": _safe_int(summary.get("scenario_count")),
        "passed_scenarios": _safe_int(summary.get("passed_scenarios")),
        "pass_rate": derived.get("pass_rate"),
        "by_error_code": derived.get("by_error_code", {}),
        "scenario_rows": scenario_rows,
        "false_accept_count": derived.get("false_accept_count", 0),
        "false_reject_count": derived.get("false_reject_count", 0),
        "wrong_error_code_count": derived.get("wrong_error_code_count", 0),
    }


def _load_run_records(run: dict[str, Any]) -> list[dict[str, Any]]:
    json_path_value = run.get("json_path")
    if not isinstance(json_path_value, str):
        return []
    json_path = Path(json_path_value)
    try:
        payload = _load_json(json_path)
    except (OSError, ValueError, json.JSONDecodeError):
        return []
    records = payload.get("records")
    return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []


def derive_evidence_validity(
    benchmark_status: dict[str, dict[str, Any] | None],
    *,
    runtime_health: dict[str, Any],
    load_errors: list[dict[str, str]],
    latency: dict[str, Any],
    reliability: dict[str, Any],
    safety: dict[str, Any],
) -> dict[str, Any]:
    warnings: list[dict[str, str]] = []

    for name in BENCHMARK_NAMES:
        if benchmark_status.get(name) is None:
            warnings.append(_warning(f"missing_{name}", f"No latest {name} benchmark artifact was found.", severity="critical"))

    if load_errors:
        warnings.append(_warning("artifact_load_errors", f"{len(load_errors)} benchmark artifact(s) could not be loaded.", severity="critical"))

    reliability_run = benchmark_status.get("reliability")
    safety_run = benchmark_status.get("safety")
    if isinstance(reliability_run, dict) and reliability_run.get("passed") is False:
        warnings.append(_warning("reliability_failed", "The latest reliability benchmark failed.", severity="critical"))
    if isinstance(safety_run, dict) and safety_run.get("passed") is False:
        warnings.append(_warning("safety_failed", "The latest safety benchmark failed.", severity="critical"))

    latency_n = _safe_int(latency.get("sample_count"))
    if latency_n is not None and latency_n < MIN_LATENCY_SAMPLES:
        warnings.append(_warning("low_latency_sample_count", f"Latency has n={latency_n}; target at least {MIN_LATENCY_SAMPLES} samples."))

    iterations = _safe_int(reliability.get("iterations"))
    if iterations is not None and iterations < MIN_RELIABILITY_ITERATIONS:
        warnings.append(_warning("low_reliability_iterations", f"Reliability has {iterations} iteration(s); target at least {MIN_RELIABILITY_ITERATIONS}."))

    scenario_count = _safe_int(safety.get("scenario_count"))
    if scenario_count is not None and scenario_count < MIN_SAFETY_SCENARIOS:
        warnings.append(_warning("low_safety_coverage", f"Safety covers {scenario_count} scenario(s); target at least {MIN_SAFETY_SCENARIOS}."))

    for name, run in benchmark_status.items():
        if not isinstance(run, dict):
            continue
        git = _metadata_git(run)
        env = _metadata_env(run)
        if not git.get("commit"):
            warnings.append(_warning(f"{name}_missing_git_commit", f"{name} run is missing a git commit."))
        if git.get("dirty") is True:
            warnings.append(_warning(f"{name}_dirty_git", f"{name} run was captured from a dirty worktree."))
        if str(env.get("backend_mode") or "").lower() in {"mock", "local"}:
            warnings.append(_warning(f"{name}_non_live_backend", f"{name} run used backend_mode={env.get('backend_mode')}.", severity="critical"))

    runtime_mode = str(runtime_health.get("backend_mode") or "").lower()
    if runtime_mode in {"mock", "local"}:
        warnings.append(_warning("runtime_non_live_backend", f"Current runtime uses backend_mode={runtime_health.get('backend_mode')}."))

    has_critical = any(warning["severity"] == "critical" for warning in warnings)
    return {
        "is_valid_evidence": not has_critical,
        "critical_count": sum(1 for warning in warnings if warning["severity"] == "critical"),
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def _thesis_number_rows(latency: dict[str, Any], reliability: dict[str, Any], safety: dict[str, Any]) -> list[dict[str, Any]]:
    latency_ms = latency.get("latency_ms") if isinstance(latency.get("latency_ms"), dict) else {}
    confirmed_ms = (
        latency.get("confirmed_action_latency_ms")
        if isinstance(latency.get("confirmed_action_latency_ms"), dict)
        else {}
    )
    duration_s = reliability.get("duration_s") if isinstance(reliability.get("duration_s"), dict) else {}
    return [
        {"metric": "Tool-call latency mean", "value": latency_ms.get("mean"), "unit": "ms", "source": "latency"},
        {"metric": "Tool-call latency p95", "value": latency_ms.get("p95"), "unit": "ms", "source": "latency"},
        {"metric": "Tool-call latency p99", "value": latency_ms.get("p99"), "unit": "ms", "source": "latency"},
        {"metric": "Confirmed arm/disarm latency mean", "value": confirmed_ms.get("mean"), "unit": "ms", "source": "latency"},
        {"metric": "Nominal mission success rate", "value": reliability.get("success_rate"), "unit": "ratio", "source": "reliability"},
        {"metric": "Recovery to ready rate", "value": reliability.get("recovery_to_ready_rate"), "unit": "ratio", "source": "reliability"},
        {"metric": "Nominal mission mean duration", "value": duration_s.get("mean"), "unit": "s", "source": "reliability"},
        {"metric": "Safety rejection correctness rate", "value": safety.get("pass_rate"), "unit": "ratio", "source": "safety"},
        {"metric": "Safety false accepts", "value": safety.get("false_accept_count"), "unit": "count", "source": "safety"},
        {"metric": "Safety wrong error codes", "value": safety.get("wrong_error_code_count"), "unit": "count", "source": "safety"},
    ]


def benchmark_headline(
    benchmark: str,
    summary: dict[str, Any],
    derived: dict[str, Any],
    *,
    record_count: int,
) -> str:
    if benchmark == "latency":
        latency = derived.get("latency_ms", {})
        mean_ms = latency.get("mean") if isinstance(latency, dict) else summary.get("mean_latency_ms")
        p95_ms = latency.get("p95") if isinstance(latency, dict) else None
        if isinstance(mean_ms, (int, float)) and isinstance(p95_ms, (int, float)):
            return f"{mean_ms:.1f} ms mean | {p95_ms:.1f} ms p95"
    if benchmark == "reliability":
        successful = summary.get("successful_iterations")
        iterations = summary.get("iterations")
        success_rate = summary.get("success_rate")
        if isinstance(successful, int) and isinstance(iterations, int):
            if isinstance(success_rate, (int, float)):
                return f"{successful}/{iterations} passes | {success_rate * 100:.0f}% success"
            return f"{successful}/{iterations} passes"
    if benchmark == "safety":
        passed = summary.get("passed_scenarios")
        scenarios = summary.get("scenario_count")
        if isinstance(passed, int) and isinstance(scenarios, int):
            return f"{passed}/{scenarios} checks passed"
    return f"{record_count} records captured" if record_count else "Summary available"


def write_csv_export(path: Path, rows: list[dict[str, Any]]) -> None:
    field_names: list[str] = []
    seen_fields: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen_fields:
                field_names.append(key)
                seen_fields.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=field_names or ["record"])
        writer.writeheader()
        writer.writerows(rows)
