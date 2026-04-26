from __future__ import annotations

import json

from uav_mcp_server.observability import (
    ObservabilityEvent,
    ObservabilityService,
    ObservabilityStore,
    latency_stats,
    percentile,
)


def _write_results(tmp_path, name: str, timestamp: str, summary: dict, records: list[dict]) -> None:
    run_dir = tmp_path / "evaluation" / "results" / f"{name}-{timestamp}"
    run_dir.mkdir(parents=True)
    (run_dir / "results.json").write_text(
        json.dumps({"metadata": {"git": {"commit": "abc123"}}, "summary": summary, "records": records}),
        encoding="utf-8",
    )
    (run_dir / "results.csv").write_text("ok\n", encoding="utf-8")


def test_percentile_interpolates_sorted_values() -> None:
    assert percentile([100, 10, 20, 30], 50) == 25.0
    assert percentile([10, 20, 30, 100], 95) == 89.5


def test_latency_stats_returns_thesis_percentiles() -> None:
    stats = latency_stats([10, 20, 30, 100])

    assert stats["count"] == 4
    assert stats["mean"] == 40.0
    assert stats["p50"] == 25.0
    assert stats["p95"] == 89.5


def test_observability_service_summarizes_benchmark_artifacts(tmp_path) -> None:
    _write_results(
        tmp_path,
        "latency",
        "20260420T100000Z",
        {"benchmark": "latency", "iterations": 2, "sample_count": 4},
        [
            {"tool": "get_status", "latency_ms": 10.0, "success": True},
            {"tool": "get_status", "latency_ms": 20.0, "success": True},
            {"tool": "arm", "latency_ms": 400.0, "success": True},
            {"tool": "arm", "latency_ms": 600.0, "success": True},
        ],
    )
    _write_results(
        tmp_path,
        "reliability",
        "20260420T110000Z",
        {
            "benchmark": "reliability",
            "iterations": 2,
            "successful_iterations": 2,
            "success_rate": 1.0,
            "passed": True,
        },
        [{"iteration": 1, "success": True, "duration_s": 12.5}],
    )
    _write_results(
        tmp_path,
        "safety",
        "20260420T120000Z",
        {
            "benchmark": "safety",
            "scenario_count": 2,
            "passed_scenarios": 2,
            "passed": True,
        },
        [
            {
                "scenario": "geofence_violation",
                "error_code": "geofence_violation",
                "expected_error_code": "geofence_violation",
                "passed": True,
            }
        ],
    )

    service = ObservabilityService(
        tmp_path,
        store=ObservabilityStore(tmp_path / ".run" / "observability.sqlite3"),
    )

    summary = service.summary()

    assert summary["readiness"]["complete_suite"] is True
    assert summary["readiness"]["ready_for_thesis"] is True
    assert summary["benchmarks"]["latency"]["metadata"]["git"]["commit"] == "abc123"
    assert summary["benchmarks"]["latency"]["derived"]["by_tool"]["arm"]["p50"] == 500.0
    assert summary["benchmarks"]["safety"]["derived"]["pass_rate"] == 1.0


def test_observability_store_records_runtime_events(tmp_path) -> None:
    store = ObservabilityStore(tmp_path / "observability.sqlite3")
    store.record(
        ObservabilityEvent(
            timestamp="2026-04-20T10:00:00.000+00:00",
            source="mcp",
            action="tool_call",
            command="goto_relative",
            success=False,
            error_code="geofence_violation",
            duration_ms=12.3,
            message="rejected",
            request={"north_m": 100},
            response={"success": False},
        )
    )

    events = store.recent()
    summary = store.summary()

    assert events[0]["command"] == "goto_relative"
    assert events[0]["request"] == {"north_m": 100}
    assert summary["event_count"] == 1
    assert summary["safety_rejection_count"] == 1
    assert summary["by_error_code"]["geofence_violation"] == 1
