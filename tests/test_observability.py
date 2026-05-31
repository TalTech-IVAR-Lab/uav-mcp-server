from __future__ import annotations

import json

from uav_mcp_server.observability import (
    ObservabilityEvent,
    ObservabilityService,
    ObservabilityStore,
    latency_stats,
    percentile,
)


def _write_results(
    tmp_path,
    name: str,
    timestamp: str,
    summary: dict,
    records: list[dict],
    metadata: dict | None = None,
) -> None:
    run_dir = tmp_path / "evaluation" / "results" / f"{name}-{timestamp}"
    run_dir.mkdir(parents=True)
    (run_dir / "results.json").write_text(
        json.dumps(
            {
                "metadata": metadata or {"git": {"commit": "abc123"}},
                "summary": summary,
                "records": records,
            }
        ),
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
    assert summary["thesis_metrics"]["tables"]["thesis_numbers"][1]["metric"] == "Tool-call latency p95"


def test_observability_service_derives_thesis_metrics_and_validity_warnings(tmp_path) -> None:
    live_metadata = {
        "git": {"commit": "abc123456", "branch": "main", "dirty": False},
        "environment": {"backend_mode": "px4"},
    }
    _write_results(
        tmp_path,
        "latency",
        "20260420T100000Z",
        {"benchmark": "latency", "iterations": 1, "sample_count": 4},
        [
            {"tool": "get_status", "latency_ms": 10.0, "success": True},
            {"tool": "get_telemetry", "latency_ms": 20.0, "success": True},
            {"tool": "arm", "latency_ms": 400.0, "success": True},
            {"tool": "disarm", "latency_ms": 600.0, "success": True},
        ],
        metadata=live_metadata,
    )
    _write_results(
        tmp_path,
        "reliability",
        "20260420T110000Z",
        {
            "benchmark": "reliability",
            "iterations": 1,
            "successful_iterations": 1,
            "success_rate": 1.0,
            "passed": True,
        },
        [
            {
                "iteration": 1,
                "success": True,
                "duration_s": 12.5,
                "final_state": "ready",
                "final_armed": False,
                "final_in_air": False,
            }
        ],
        metadata=live_metadata,
    )
    _write_results(
        tmp_path,
        "safety",
        "20260420T120000Z",
        {
            "benchmark": "safety",
            "scenario_count": 2,
            "passed_scenarios": 1,
            "passed": False,
        },
        [
            {
                "scenario": "geofence_violation",
                "success": False,
                "error_code": "geofence_violation",
                "expected_error_code": "geofence_violation",
                "passed": True,
            },
            {
                "scenario": "wrong_state",
                "success": True,
                "error_code": None,
                "expected_error_code": "wrong_state",
                "passed": False,
            },
        ],
        metadata=live_metadata,
    )

    service = ObservabilityService(
        tmp_path,
        store=ObservabilityStore(tmp_path / ".run" / "observability.sqlite3"),
    )

    thesis = service.summary()["thesis_metrics"]

    assert thesis["latency"]["sample_count"] == 4
    assert thesis["latency"]["confirmed_action_latency_ms"]["mean"] == 500.0
    assert thesis["reliability"]["recovery_to_ready_rate"] == 1.0
    assert thesis["safety"]["false_accept_count"] == 1
    assert thesis["validity"]["is_valid_evidence"] is False
    assert {warning["code"] for warning in thesis["validity"]["warnings"]} >= {
        "safety_failed",
        "low_latency_sample_count",
        "low_reliability_iterations",
        "low_safety_coverage",
    }


def test_observability_export_includes_thesis_metric_tables(tmp_path) -> None:
    _write_results(
        tmp_path,
        "latency",
        "20260420T100000Z",
        {"benchmark": "latency", "iterations": 1, "sample_count": 1},
        [{"tool": "get_status", "latency_ms": 10.0, "success": True}],
    )

    service = ObservabilityService(
        tmp_path,
        store=ObservabilityStore(tmp_path / ".run" / "observability.sqlite3"),
    )

    exported = service.export()

    assert "thesis_metrics" in exported
    assert exported["thesis_metrics"]["tables"]["thesis_numbers"][0]["source"] == "latency"


def test_observability_store_records_runtime_events(tmp_path) -> None:
    store = ObservabilityStore(tmp_path / "observability.sqlite3")
    store.record(
        ObservabilityEvent(
            timestamp="2026-04-20T10:00:00.000+00:00",
            source="mcp",
            action="command",
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
    # minutes=0 → all-time summary; the event has a hardcoded past timestamp
    # that would be outside any fixed time window.
    summary = store.summary(minutes=0)

    assert events[0]["command"] == "goto_relative"
    assert events[0]["request"] == {"north_m": 100}
    assert summary["event_count"] == 1
    assert summary["safety_rejection_count"] == 1
    assert summary["by_error_code"]["geofence_violation"] == 1
