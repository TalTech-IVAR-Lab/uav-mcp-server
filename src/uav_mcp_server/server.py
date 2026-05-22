"""FastMCP server wiring for the safe UAV control surface."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from math import atan2, degrees
from pathlib import Path
from time import monotonic
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import PromptMessage, TextContent, ToolAnnotations

from uav_mcp_server.assistant import (
    ASSISTANT_ALLOWED_COMMANDS,
    AssistantGroundingContext,
    AssistantTarget,
    DashboardAssistant,
    build_command_manifest,
    fetch_mcp_grounding,
    needs_camera_target_resolution,
    _prompt_text,
    _resource_dict,
    _resource_text,
    workflow_guide_text,
)
from uav_mcp_server.camera import CameraStreamer
from uav_mcp_server.config import Settings, get_settings
from uav_mcp_server.dashboard import DashboardState, register_dashboard_routes
from uav_mcp_server.drone import DroneController, DroneBackend, MavsdkBackend
from uav_mcp_server.local_backend import LocalSimulationBackend
from uav_mcp_server.navigation import coordinate_offset_m
from uav_mcp_server.navigation import haversine_distance_m
from uav_mcp_server.observability import ObservabilityEvent, ObservabilityService, now_iso
from uav_mcp_server.projection import CameraParams, DronePose, pixel_to_world
from uav_mcp_server.terrain import HeightmapSpec, TerrainSampler
from uav_mcp_server.command_queue import CommandQueue, QueueEntry
from uav_mcp_server.safety import RATE_LIMIT_EXEMPT_COMMANDS, SafetyValidator
from uav_mcp_server.telemetry import TelemetryManager
from uav_mcp_server.types import (
    CommandResult,
    DroneState,
    ErrorCode,
    OrbitYawBehavior,
    TelemetrySnapshot,
    WaypointInput,
)

SERVER_INSTRUCTIONS = (
    "Safe UAV control server for PX4 SITL. Prefer guided_takeoff for normal launch "
    "requests, keep raw takeoff for already-armed low-level use, and route all motion "
    "through safety validation. Use yaw_relative and gimbal_pitch_relative for "
    "operator/manual or AI-assisted framing when supported. Do not invent actions "
    "outside the exposed tools."
)

UTC = timezone.utc
BENCHMARK_NAMES = ("latency", "reliability", "safety")
QUEUE_BYPASS_COMMANDS = RATE_LIMIT_EXEMPT_COMMANDS
RUN_TIMESTAMP_PATTERN = re.compile(r"-(\d{8}T\d{6}Z)$")


@dataclass(slots=True)
class ServerServices:
    settings: Settings
    controller: DroneController
    safety: SafetyValidator


def build_services(
    *,
    settings: Settings | None = None,
    backend: DroneBackend | None = None,
) -> ServerServices:
    resolved_settings = settings or get_settings()
    telemetry_manager = TelemetryManager()
    controller = DroneController(
        settings=resolved_settings,
        backend=backend or _build_backend(resolved_settings),
        telemetry_manager=telemetry_manager,
    )
    return ServerServices(
        settings=resolved_settings,
        controller=controller,
        safety=SafetyValidator(resolved_settings),
    )


def _server_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _isoformat_timestamp(timestamp_s: float) -> str:
    return datetime.fromtimestamp(timestamp_s, tz=UTC).isoformat(timespec="seconds")


def _path_metadata(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path),
            "exists": False,
            "size_bytes": None,
            "updated_at": None,
        }

    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size_bytes": stat.st_size,
        "updated_at": _isoformat_timestamp(stat.st_mtime),
    }


def _read_pid_file(path: Path) -> dict[str, Any]:
    status = {
        "pid_file": str(path),
        "managed": path.exists(),
        "pid": None,
        "running": False,
    }
    if not path.exists():
        return status

    try:
        raw_value = path.read_text(encoding="utf-8").strip()
        pid = int(raw_value)
    except (OSError, ValueError):
        return status

    status["pid"] = pid
    try:
        os.kill(pid, 0)
    except OSError:
        status["running"] = False
    else:
        status["running"] = True
    return status


def _read_prefixed_log_values(
    log_path: Path,
    *prefixes: str,
    max_lines: int = 80,
) -> dict[str, str]:
    values: dict[str, str] = {}
    if not log_path.exists():
        return values

    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for index, line in enumerate(handle):
                if index >= max_lines:
                    break
                stripped = line.strip()
                for prefix in prefixes:
                    if stripped.startswith(prefix):
                        values[prefix] = stripped[len(prefix) :].strip()
    except OSError:
        return values
    return values


def _parse_run_timestamp(name: str, *, fallback_path: Path) -> str | None:
    match = RUN_TIMESTAMP_PATTERN.search(name)
    if match is not None:
        raw_value = match.group(1)
        try:
            return datetime.strptime(raw_value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC).isoformat(timespec="seconds")
        except ValueError:
            pass

    if fallback_path.exists():
        return _isoformat_timestamp(fallback_path.stat().st_mtime)
    return None


def _format_benchmark_headline(benchmark: str, summary: dict[str, Any], *, record_count: int) -> str:
    if benchmark == "latency":
        mean_latency_ms = summary.get("mean_latency_ms")
        max_latency_ms = summary.get("max_latency_ms")
        if isinstance(mean_latency_ms, (int, float)) and isinstance(max_latency_ms, (int, float)):
            return f"{mean_latency_ms:.1f} ms mean | {max_latency_ms:.1f} ms max"
    elif benchmark == "reliability":
        successful_iterations = summary.get("successful_iterations")
        iterations = summary.get("iterations")
        success_rate = summary.get("success_rate")
        if isinstance(successful_iterations, int) and isinstance(iterations, int):
            if isinstance(success_rate, (int, float)):
                return f"{successful_iterations}/{iterations} passes | {success_rate * 100:.0f}% success"
            return f"{successful_iterations}/{iterations} passes"
    elif benchmark == "safety":
        passed_scenarios = summary.get("passed_scenarios")
        scenario_count = summary.get("scenario_count")
        if isinstance(passed_scenarios, int) and isinstance(scenario_count, int):
            return f"{passed_scenarios}/{scenario_count} checks passed"

    if record_count > 0:
        return f"{record_count} records captured"
    return "Summary available"


def _collect_evaluation_summary(repo_root: Path) -> dict[str, Any]:
    results_dir = repo_root / "evaluation" / "results"
    benchmark_summaries: dict[str, dict[str, Any]] = {}
    latest_run: dict[str, Any] | None = None
    load_errors: list[dict[str, str]] = []
    run_count = 0

    if results_dir.exists():
        for json_path in sorted(results_dir.glob("*/results.json")):
            try:
                payload = json.loads(json_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                load_errors.append({"path": str(json_path), "message": str(exc)})
                continue

            summary = payload.get("summary")
            if not isinstance(summary, dict):
                load_errors.append({"path": str(json_path), "message": "results.json is missing a summary object"})
                continue

            records = payload.get("records")
            record_count = len(records) if isinstance(records, list) else 0
            benchmark_name = str(summary.get("benchmark") or json_path.parent.name.split("-", 1)[0]).strip().lower()
            run_timestamp = _parse_run_timestamp(json_path.parent.name, fallback_path=json_path)
            passed_value = summary.get("passed")
            passed = passed_value if isinstance(passed_value, bool) else None
            entry = {
                "benchmark": benchmark_name,
                "run_dir": str(json_path.parent),
                "json_path": str(json_path),
                "csv_path": str(json_path.parent / "results.csv"),
                "timestamp": run_timestamp,
                "record_count": record_count,
                "summary": summary,
                "passed": passed,
                "headline": _format_benchmark_headline(benchmark_name, summary, record_count=record_count),
            }

            run_count += 1
            if latest_run is None or (entry["timestamp"] or "") > (latest_run.get("timestamp") or ""):
                latest_run = entry

            current = benchmark_summaries.get(benchmark_name)
            if current is None or (entry["timestamp"] or "") > (current.get("timestamp") or ""):
                benchmark_summaries[benchmark_name] = entry

    readiness = {
        "has_results": bool(benchmark_summaries),
        "has_latency": "latency" in benchmark_summaries,
        "has_reliability": "reliability" in benchmark_summaries,
        "has_safety": "safety" in benchmark_summaries,
        "reliability_passed": benchmark_summaries.get("reliability", {}).get("passed"),
        "safety_passed": benchmark_summaries.get("safety", {}).get("passed"),
    }
    readiness["complete_suite"] = all(readiness[f"has_{name}"] for name in BENCHMARK_NAMES)
    readiness["ready_for_review"] = (
        readiness["complete_suite"]
        and readiness["reliability_passed"] is True
        and readiness["safety_passed"] is True
    )

    if readiness["ready_for_review"]:
        summary_line = "Latest latency, reliability, and safety artifacts are available and the pass/fail suite is green."
    elif latest_run is not None:
        summary_line = f"Latest artifact: {latest_run['benchmark']} at {latest_run['timestamp'] or 'unknown time'}."
    else:
        summary_line = "No evaluation artifacts found. Run the CLI benchmarks to populate evaluation/results."

    return {
        "results_dir": str(results_dir),
        "results_dir_exists": results_dir.exists(),
        "run_count": run_count,
        "latest_run": latest_run,
        "benchmarks": {name: benchmark_summaries.get(name) for name in BENCHMARK_NAMES},
        "readiness": readiness,
        "summary_line": summary_line,
        "load_errors": load_errors,
    }


def _build_backend(settings: Settings) -> DroneBackend:
    if settings.backend_mode == "local":
        return LocalSimulationBackend(
            home_latitude_deg=settings.geofence_center_lat,
            home_longitude_deg=settings.geofence_center_lon,
        )
    return MavsdkBackend()


def create_server(
    services: ServerServices | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    resolved_services = services or build_services()
    camera_streamer = CameraStreamer(
        enabled=resolved_services.settings.camera_enabled,
        topic=resolved_services.settings.camera_ros_topic,
        fps=resolved_services.settings.camera_fps,
        helper_python_bin=resolved_services.settings.camera_helper_python_bin,
        ros_setup_script=resolved_services.settings.camera_ros_setup_script,
        helper_gazebo_topic_suffix=resolved_services.settings.camera_gazebo_topic_suffix,
    )
    camera_params = CameraParams(
        width_px=resolved_services.settings.camera_width_px,
        height_px=resolved_services.settings.camera_height_px,
        hfov_rad=resolved_services.settings.camera_hfov_rad,
        focal_length_px=resolved_services.settings.camera_focal_length_px,
        mount_yaw_deg=resolved_services.settings.camera_mount_yaw_deg,
        mount_pitch_deg=resolved_services.settings.camera_mount_pitch_deg,
        mount_roll_deg=resolved_services.settings.camera_mount_roll_deg,
    )
    # Best-effort: replace the .env intrinsics with what gz is actually
    # rendering. gz publishes the K matrix on each camera's camera_info topic
    # — using it eliminates drift between SDF hfov, .env values, and the
    # renderer. Failures (no `gz` CLI on PATH, sim not running, topic timeout)
    # silently fall back to the .env-derived params above.
    try:
        from uav_mcp_server.camera_intrinsics import probe_camera_intrinsics_via_gz

        live_intrinsics = probe_camera_intrinsics_via_gz(
            gazebo_topic_suffix=resolved_services.settings.camera_gazebo_topic_suffix,
            timeout_s=3.0,
        )
        if live_intrinsics is not None:
            camera_params = CameraParams(
                width_px=live_intrinsics["width_px"],
                height_px=live_intrinsics["height_px"],
                hfov_rad=camera_params.hfov_rad,  # not in K, keep .env
                focal_length_px=live_intrinsics["fx"],
                mount_yaw_deg=camera_params.mount_yaw_deg,
                mount_pitch_deg=camera_params.mount_pitch_deg,
                mount_roll_deg=camera_params.mount_roll_deg,
                principal_x_px=live_intrinsics["cx"],
                principal_y_px=live_intrinsics["cy"],
            )
            import logging as _logging
            _logging.getLogger(__name__).info(
                "Camera intrinsics loaded from gz camera_info: "
                "fx=%.3f fy=%.3f cx=%.1f cy=%.1f %dx%d",
                live_intrinsics["fx"], live_intrinsics["fy"],
                live_intrinsics["cx"], live_intrinsics["cy"],
                live_intrinsics["width_px"], live_intrinsics["height_px"],
            )
    except Exception as intrinsics_exc:  # noqa: BLE001
        import logging as _logging
        _logging.getLogger(__name__).debug(
            "Live camera intrinsics probe failed (%s); using .env values.",
            intrinsics_exc,
        )
    # Optional terrain-aware projection: loads the TalTech heightmap PNG so
    # camera target selection iterates against the real ground elevation
    # instead of assuming flat ground at home altitude. Missing PNG or
    # missing Pillow falls back silently to the flat-ground path.
    terrain_sampler: TerrainSampler | None
    try:
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[2]
        spec = HeightmapSpec.taltech_default(repo_root)
        if spec.png_path.exists():
            terrain_sampler = TerrainSampler(spec)
        else:
            terrain_sampler = None
    except Exception as terrain_exc:  # noqa: BLE001 - intentionally broad
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Terrain sampler unavailable, falling back to flat-ground projection: %s",
            terrain_exc,
        )
        terrain_sampler = None
    mcp = FastMCP(
        name="UAV Control Server",
        instructions=SERVER_INSTRUCTIONS,
        json_response=True,
        stateless_http=True,
        log_level=resolved_services.settings.log_level.upper(),
        host=host,
        port=port,
    )

    def current_snapshot() -> TelemetrySnapshot:
        return resolved_services.controller.telemetry_manager.get_snapshot()

    def validate(command_name: str, **kwargs: Any) -> CommandResult | None:
        return resolved_services.safety.validate(command_name, current_snapshot(), **kwargs)

    def current_drone_pose() -> DronePose:
        snapshot = current_snapshot()
        if (
            snapshot.latitude_deg is None
            or snapshot.longitude_deg is None
            or snapshot.absolute_altitude_m is None
            or snapshot.relative_altitude_m is None
        ):
            raise RuntimeError("Telemetry pose is incomplete; projection is not available yet.")
        pitch_deg = snapshot.pitch_deg or 0.0
        roll_deg = snapshot.roll_deg or 0.0
        if resolved_services.settings.camera_stabilized:
            pitch_deg = 0.0
            roll_deg = 0.0
        return DronePose(
            lat_deg=snapshot.latitude_deg,
            lon_deg=snapshot.longitude_deg,
            absolute_altitude_m=snapshot.absolute_altitude_m,
            relative_altitude_m=snapshot.relative_altitude_m,
            home_absolute_altitude_m=snapshot.inferred_home_absolute_altitude_m(),
            yaw_deg=snapshot.yaw_deg or 0.0,
            pitch_deg=pitch_deg,
            roll_deg=roll_deg,
        )

    assistant = DashboardAssistant(resolved_services.settings)
    manual_window: deque[float] = deque()
    repo_root = _server_repo_root()
    observability = ObservabilityService(repo_root)
    command_queue = CommandQueue(
        max_depth=resolved_services.settings.command_queue_max_depth,
        rate_limit_per_sec=resolved_services.settings.command_rate_limit_per_sec,
    )
    local_backend_active = isinstance(getattr(resolved_services.controller, "_backend", None), LocalSimulationBackend)
    gimbal_state: dict[str, Any]
    if not resolved_services.settings.manual_control_supports_gimbal_pitch:
        gimbal_state = {
            "status": "disabled",
            "available": False,
            "reason": "Gimbal control is disabled in the current settings.",
            "last_checked_at": None,
            "last_source": "settings",
        }
    elif local_backend_active:
        gimbal_state = {
            "status": "available",
            "available": True,
            "reason": "Local simulation backend exposes gimbal controls.",
            "last_checked_at": None,
            "last_source": "backend_mode",
        }
    else:
        gimbal_state = {
            "status": "unknown",
            "available": None,
            "reason": "No non-invasive probe has confirmed live gimbal support yet.",
            "last_checked_at": None,
            "last_source": "startup",
        }

    def _record_gimbal_result(result: CommandResult, *, source: str) -> None:
        if not resolved_services.settings.manual_control_supports_gimbal_pitch:
            return

        gimbal_state["last_checked_at"] = datetime.now(tz=UTC).isoformat(timespec="seconds")
        gimbal_state["last_source"] = source
        gimbal_state["tracked_pitch_deg"] = resolved_services.controller.current_gimbal_pitch_deg()
        gimbal_state["tracked_yaw_deg"] = resolved_services.controller.current_gimbal_yaw_deg()

        if result.success:
            gimbal_state["status"] = "available"
            gimbal_state["available"] = True
            gimbal_state["reason"] = result.message
            return

        if result.error_code == ErrorCode.NOT_IMPLEMENTED:
            gimbal_state["status"] = "unavailable"
            gimbal_state["available"] = False
            gimbal_state["reason"] = result.message
            return

        if result.error_code == ErrorCode.CONNECTION_LOST and gimbal_state.get("available") is None:
            gimbal_state["status"] = "unknown"
            gimbal_state["reason"] = result.message
            return

        gimbal_state["status"] = "degraded"
        gimbal_state["reason"] = result.message

    def _camera_status_dict() -> dict[str, Any]:
        return camera_streamer.status().to_dict()

    def _runtime_context() -> dict[str, Any]:
        settings = resolved_services.settings
        run_dir = repo_root / ".run"
        logs_dir = run_dir / "logs"
        sitl_log_path = logs_dir / "sitl.log"
        server_log_path = logs_dir / "server.log"
        sitl_values = _read_prefixed_log_values(
            sitl_log_path,
            "Runtime:",
            "Model:",
            "Make target:",
            "World:",
        )
        runtime_name = sitl_values.get("Runtime:")
        requested_model = sitl_values.get("Model:")
        make_target = sitl_values.get("Make target:")
        world_value = sitl_values.get("World:")

        if settings.backend_mode == "local":
            runtime_name = runtime_name or "local"
            requested_model = requested_model or "local"
            make_target = make_target or "local-simulation"
            world_label = "not_applicable"
            world_path = None
            world_exists = None
        else:
            world_path = world_value if world_value and world_value != "default" else None
            if world_path is not None:
                world_label = Path(world_path).name
                world_exists = Path(world_path).exists()
            else:
                world_label = f"{settings.sim_classic_world_name}.world"
                inferred_world_path = repo_root / "sim" / "gazebo-classic" / "worlds" / world_label
                world_path = str(inferred_world_path) if inferred_world_path.exists() else None
                world_exists = inferred_world_path.exists() if world_path is not None else None

        sitl_pid = _read_pid_file(run_dir / "sitl.pid")
        server_pid = _read_pid_file(run_dir / "server.pid")
        snapshot = current_snapshot()

        stack_status = "healthy"
        if settings.backend_mode == "live" and sitl_pid["managed"] and not sitl_pid["running"]:
            stack_status = "degraded"
        elif settings.backend_mode == "live" and not sitl_pid["managed"]:
            stack_status = "external"
        elif not snapshot.connected and settings.backend_mode == "live":
            stack_status = "idle"

        stack_summary_parts = [f"backend {settings.backend_mode}"]
        if runtime_name:
            stack_summary_parts.append(runtime_name)
        if make_target:
            stack_summary_parts.append(make_target)
        if snapshot.connected:
            stack_summary_parts.append("telemetry linked")
        else:
            stack_summary_parts.append("telemetry idle")

        return {
            "backend_mode": settings.backend_mode,
            "airframe": {
                "requested_model": requested_model,
                "make_target": make_target,
                "runtime": runtime_name,
                "label": make_target or requested_model or settings.backend_mode,
                "source": "sitl_log" if sitl_values else ("settings" if settings.backend_mode == "local" else "fallback"),
            },
            "world": {
                "label": world_label,
                "path": world_path,
                "exists": world_exists,
                "source": "sitl_log" if world_value else ("settings" if settings.backend_mode != "local" else "backend_mode"),
            },
            "stack": {
                "status": stack_status,
                "summary": " | ".join(part for part in stack_summary_parts if part),
                "server": {
                    "running": True,
                    "process_id": os.getpid(),
                    "managed_pid": server_pid["pid"],
                    "managed": server_pid["managed"],
                    "log": _path_metadata(server_log_path),
                },
                "sitl": {
                    **sitl_pid,
                    "log": _path_metadata(sitl_log_path),
                },
            },
        }

    def _runtime_readiness(camera_status: dict[str, Any], evaluation_summary: dict[str, Any]) -> dict[str, Any]:
        settings = resolved_services.settings
        snapshot = current_snapshot()
        pose_ready = all(
            value is not None
            for value in (
                snapshot.latitude_deg,
                snapshot.longitude_deg,
                snapshot.absolute_altitude_m,
                snapshot.relative_altitude_m,
            )
        )
        preflight_reasons: list[str] = []
        if not snapshot.connected:
            preflight_reasons.append("backend disconnected")
        if not snapshot.is_global_position_ok or not snapshot.is_home_position_ok:
            preflight_reasons.append("global/home position not ready")
        if not snapshot.is_gyrometer_calibration_ok or not snapshot.is_accelerometer_calibration_ok:
            preflight_reasons.append("sensor calibration incomplete")
        if snapshot.battery_percent is None:
            preflight_reasons.append("battery telemetry unavailable")
        elif snapshot.battery_percent < settings.min_battery_percent:
            preflight_reasons.append(
                f"battery {snapshot.battery_percent:.0f}% < {settings.min_battery_percent}%"
            )

        preflight_ready = not preflight_reasons
        launch_ready = preflight_ready and snapshot.state in {
            DroneState.DISCONNECTED,
            DroneState.CONNECTED,
            DroneState.READY,
            DroneState.ARMED,
        }
        gimbal_available = gimbal_state.get("available")
        flags = {
            "telemetry_link": snapshot.connected,
            "pose": pose_ready,
            "preflight": preflight_ready,
            "launch": launch_ready,
            "camera": bool(camera_status.get("enabled")) and bool(camera_status.get("available")),
            "gimbal": gimbal_available is True,
            "evaluation": bool(evaluation_summary.get("readiness", {}).get("ready_for_review")),
        }

        if flags["launch"]:
            summary = "Guided takeoff path is ready."
        elif preflight_reasons:
            summary = "Preflight blockers: " + "; ".join(preflight_reasons)
        elif snapshot.in_air:
            summary = "Vehicle is airborne; launch readiness is not applicable."
        else:
            summary = "Waiting for telemetry and preflight readiness."

        return {
            "flags": flags,
            "summary": summary,
            "preflight_reasons": preflight_reasons,
        }

    def _dashboard_runtime_health() -> dict[str, Any]:
        camera_status = _camera_status_dict()
        evaluation_summary = _collect_evaluation_summary(repo_root)
        context = _runtime_context()
        readiness = _runtime_readiness(camera_status, evaluation_summary)
        snapshot = current_snapshot()
        return {
            "timestamp": datetime.now(tz=UTC).isoformat(timespec="seconds"),
            "backend_mode": resolved_services.settings.backend_mode,
            "airframe": context["airframe"],
            "world": context["world"],
            "stack": context["stack"],
            "telemetry": {
                "state": snapshot.state.value,
                "connected": snapshot.connected,
                "flight_mode": snapshot.flight_mode,
            },
            "camera": camera_status,
            "gimbal": {
                **gimbal_state,
                "configured": resolved_services.settings.manual_control_supports_gimbal_pitch,
            },
            "readiness": readiness,
        }

    def _dashboard_evaluation_summary() -> dict[str, Any]:
        return _collect_evaluation_summary(repo_root)

    def _assistant_mcp_url() -> str:
        configured_url = getattr(resolved_services.settings, "assistant_mcp_url", None)
        if configured_url:
            return configured_url
        if host in {"0.0.0.0", "::", ""}:
            endpoint_host = "127.0.0.1"
        else:
            endpoint_host = host
        return f"http://{endpoint_host}:{port}/mcp"

    def _check_manual_rate() -> CommandResult | None:
        now = monotonic()
        while manual_window and now - manual_window[0] > 1.0:
            manual_window.popleft()
        if len(manual_window) >= resolved_services.settings.manual_control_rate_limit_per_sec:
            return CommandResult.fail(
                "Manual control rate limit exceeded.",
                ErrorCode.RATE_LIMITED,
                data={
                    "limit_per_sec": resolved_services.settings.manual_control_rate_limit_per_sec,
                    "scope": "manual_control",
                },
            )
        manual_window.append(now)
        return None

    def _record_observability_event(
        *,
        source: str,
        action: str,
        command_name: str | None,
        params: dict[str, Any] | None,
        started_at: float,
        result: CommandResult | TelemetrySnapshot | dict[str, Any],
        telemetry_before: TelemetrySnapshot,
    ) -> None:
        duration_ms = round((monotonic() - started_at) * 1000.0, 3)
        telemetry_after = current_snapshot()
        if isinstance(result, CommandResult):
            success = result.success
            error_code = result.error_code.value if result.error_code is not None else None
            message = result.message
            response: dict[str, Any] | None = result.model_dump(mode="json")
        elif isinstance(result, TelemetrySnapshot):
            success = True
            error_code = None
            message = "Telemetry retrieved."
            response = result.model_dump(mode="json")
        else:
            success = True
            error_code = None
            message = None
            response = result

        observability.record_event(
            ObservabilityEvent(
                timestamp=now_iso(),
                source=source,
                action=action,
                command=command_name,
                success=success,
                error_code=error_code,
                duration_ms=duration_ms,
                message=message,
                request=params or {},
                response=response,
                telemetry_before=telemetry_before.model_dump(mode="json"),
                telemetry_after=telemetry_after.model_dump(mode="json"),
            )
        )

    async def _execute_observed(
        command_name: str,
        params: dict[str, Any],
        runner: Any,
        *,
        source: str = "mcp",
        validate_params: dict[str, Any] | None = None,
    ) -> CommandResult:
        started_at = monotonic()
        telemetry_before = current_snapshot()
        violation = validate(command_name, **(validate_params if validate_params is not None else params))
        if violation is not None:
            _record_observability_event(
                source=source,
                action="command",
                command_name=command_name,
                params=params,
                started_at=started_at,
                result=violation,
                telemetry_before=telemetry_before,
            )
            return violation

        result = await runner()
        _record_observability_event(
            source=source,
            action="command",
            command_name=command_name,
            params=params,
            started_at=started_at,
            result=result,
            telemetry_before=telemetry_before,
        )
        return result

    async def _observed_command(
        command_name: str,
        params: dict[str, Any],
        runner: Any,
        *,
        source: str = "mcp",
        validate_params: dict[str, Any] | None = None,
    ) -> CommandResult:
        if (
            not resolved_services.settings.command_queue_enabled
            or command_name in QUEUE_BYPASS_COMMANDS
            or source != "mcp"
        ):
            return await _execute_observed(
                command_name, params, runner, source=source, validate_params=validate_params
            )

        # Eager pre-validate: catch wrong-state errors immediately; skip rate limit
        # since the queue worker paces execution to respect the rate window.
        pre_params = {**(validate_params if validate_params is not None else params), "enforce_rate_limit": False}
        violation = validate(command_name, **pre_params)
        if violation is not None:
            return violation

        future: asyncio.Future[CommandResult] = asyncio.get_running_loop().create_future()
        entry = QueueEntry(
            command_name=command_name,
            runner=lambda: _execute_observed(
                command_name, params, runner, source=source, validate_params=validate_params
            ),
            future=future,
            source=source,
        )
        return await command_queue.enqueue(entry)

    async def _command_manifest() -> list[dict[str, Any]]:
        return build_command_manifest(await mcp.list_tools())

    async def _local_assistant_grounding() -> AssistantGroundingContext:
        workflow_result = await mcp.read_resource("uav://guide/workflows")
        safety_result = await mcp.read_resource("uav://config/safety")
        prompt_result = await mcp.get_prompt("operator_workflow_brief")
        return AssistantGroundingContext(
            source="mcp_local",
            command_manifest=await _command_manifest(),
            server_instructions=SERVER_INSTRUCTIONS,
            workflow_guide=_resource_text(workflow_result),
            operator_prompt=_prompt_text(prompt_result.messages),
            safety_config=_resource_dict(safety_result),
        )

    async def _assistant_grounding() -> AssistantGroundingContext:
        if assistant.api_available:
            try:
                return await fetch_mcp_grounding(_assistant_mcp_url())
            except Exception:
                pass
        return await _local_assistant_grounding()

    @mcp.tool(
        title="Connect",
        description=(
            "Connect to the active PX4 backend. Use when the vehicle is disconnected "
            "or needs a fresh backend session."
        ),
        annotations=ToolAnnotations(title="Connect"),
    )
    async def connect(connection_string: str | None = None) -> CommandResult:
        return await _observed_command(
            "connect",
            {"connection_string": connection_string},
            lambda: resolved_services.controller.connect(connection_string),
        )

    @mcp.tool(
        title="Guided Takeoff",
        description=(
            "Preferred launch workflow. Connects if needed, arms if needed, then "
            "takes off to the requested altitude using the existing safety flow."
        ),
        annotations=ToolAnnotations(title="Guided Takeoff", destructiveHint=True),
    )
    async def guided_takeoff(
        altitude_m: float = resolved_services.settings.default_takeoff_altitude_m,
        connection_string: str | None = None,
    ) -> CommandResult:
        return await _observed_command(
            "guided_takeoff",
            {"altitude_m": altitude_m, "connection_string": connection_string},
            lambda: resolved_services.controller.guided_takeoff(
                altitude_m=altitude_m,
                connection_string=connection_string,
            ),
        )

    @mcp.tool(
        title="Arm",
        description="Run preflight validation and arm the vehicle.",
        annotations=ToolAnnotations(title="Arm", destructiveHint=True),
    )
    async def arm() -> CommandResult:
        return await _observed_command("arm", {}, resolved_services.controller.arm)

    @mcp.tool(
        title="Disarm",
        description="Disarm the vehicle after landing or during a safe stop.",
        annotations=ToolAnnotations(title="Disarm", destructiveHint=True),
    )
    async def disarm() -> CommandResult:
        return await _observed_command("disarm", {}, resolved_services.controller.disarm)

    @mcp.tool(
        title="Takeoff",
        description=(
            "Low-level takeoff command. The vehicle must already be armed before "
            "this tool is used."
        ),
        annotations=ToolAnnotations(title="Takeoff", destructiveHint=True),
    )
    async def takeoff(
        altitude_m: float = resolved_services.settings.default_takeoff_altitude_m,
    ) -> CommandResult:
        return await _observed_command(
            "takeoff",
            {"altitude_m": altitude_m},
            lambda: resolved_services.controller.takeoff(altitude_m),
        )

    @mcp.tool(
        title="Land",
        description="Initiate a controlled landing sequence.",
        annotations=ToolAnnotations(title="Land", destructiveHint=True),
    )
    async def land() -> CommandResult:
        return await _observed_command("land", {}, resolved_services.controller.land)

    @mcp.tool(
        title="Hold",
        description="Pause motion and maintain the current position.",
        annotations=ToolAnnotations(title="Hold", destructiveHint=True),
    )
    async def hold() -> CommandResult:
        return await _observed_command("hold", {}, resolved_services.controller.hold)

    @mcp.tool(
        title="RTL",
        description="Return the vehicle to launch using the safety-gated path.",
        annotations=ToolAnnotations(title="RTL", destructiveHint=True),
    )
    async def rtl() -> CommandResult:
        return await _observed_command("rtl", {}, resolved_services.controller.rtl)

    @mcp.tool(
        title="Relative Move",
        description=(
            "Move by a bounded north/east offset while preserving the current heading "
            "unless an explicit yaw tool is used separately."
        ),
        annotations=ToolAnnotations(title="Relative Move", destructiveHint=True),
    )
    async def goto_relative(
        north_m: float,
        east_m: float,
        altitude_m: float,
    ) -> CommandResult:
        return await _observed_command(
            "goto_relative",
            {"north_m": north_m, "east_m": east_m, "altitude_m": altitude_m},
            lambda: resolved_services.controller.goto_relative(north_m, east_m, altitude_m),
        )

    @mcp.tool(
        title="Adjust Yaw",
        description=(
            "Rotate the vehicle by a relative heading delta while keeping the current "
            "position and altitude."
        ),
        annotations=ToolAnnotations(title="Adjust Yaw", destructiveHint=True),
    )
    async def yaw_relative(delta_deg: float) -> CommandResult:
        return await _observed_command(
            "yaw_relative",
            {"delta_deg": delta_deg},
            lambda: resolved_services.controller.yaw_relative(delta_deg),
        )

    @mcp.tool(
        title="Adjust Gimbal Pitch",
        description=(
            "Adjust the camera gimbal pitch by a relative delta when the backend "
            "supports a controllable gimbal."
        ),
        annotations=ToolAnnotations(title="Adjust Gimbal Pitch", destructiveHint=True),
    )
    async def gimbal_pitch_relative(delta_deg: float) -> CommandResult:
        result = await _observed_command(
            "gimbal_pitch_relative",
            {"delta_deg": delta_deg},
            lambda: resolved_services.controller.gimbal_pitch_relative(delta_deg),
        )
        _record_gimbal_result(result, source="tool")
        return result

    @mcp.tool(
        title="Orbit",
        description=(
            "Circle a target location with configurable radius, speed, and yaw "
            "behavior."
        ),
        annotations=ToolAnnotations(title="Orbit", destructiveHint=True),
    )
    async def orbit(
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
        radius_m: float,
        velocity_m_s: float = resolved_services.settings.default_mission_speed_m_s,
        yaw_behavior: OrbitYawBehavior = OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER,
    ) -> CommandResult:
        return await _observed_command(
            "orbit",
            {
                "latitude_deg": latitude_deg,
                "longitude_deg": longitude_deg,
                "absolute_altitude_m": absolute_altitude_m,
                "radius_m": radius_m,
                "velocity_m_s": velocity_m_s,
            },
            lambda: resolved_services.controller.orbit(
                latitude_deg=latitude_deg,
                longitude_deg=longitude_deg,
                absolute_altitude_m=absolute_altitude_m,
                radius_m=radius_m,
                velocity_m_s=velocity_m_s,
                yaw_behavior=yaw_behavior,
            ),
        )

    @mcp.tool(
        title="Run Mission",
        description="Upload a mission plan and start execution.",
        annotations=ToolAnnotations(title="Run Mission", destructiveHint=True),
    )
    async def run_mission(waypoints: list[WaypointInput]) -> CommandResult:
        return await _observed_command(
            "run_mission",
            {"waypoints": [waypoint.model_dump(mode="json") for waypoint in waypoints]},
            lambda: resolved_services.controller.run_mission(waypoints),
            validate_params={"waypoints": waypoints},
        )

    @mcp.tool(
        title="Get Status",
        description="Fetch the current vehicle state and control snapshot.",
        annotations=ToolAnnotations(
            title="Get Status",
            readOnlyHint=True,
            idempotentHint=True,
        ),
    )
    async def get_status() -> CommandResult:
        return await _observed_command("get_status", {}, resolved_services.controller.get_status)

    @mcp.tool(
        title="Get Telemetry",
        description="Fetch the current telemetry snapshot.",
        annotations=ToolAnnotations(
            title="Get Telemetry",
            readOnlyHint=True,
            idempotentHint=True,
        ),
    )
    async def get_telemetry() -> TelemetrySnapshot:
        started_at = monotonic()
        telemetry_before = current_snapshot()
        violation = validate("get_telemetry")
        result = current_snapshot() if violation is not None else await resolved_services.controller.get_telemetry()
        _record_observability_event(
            source="mcp",
            action="command",
            command_name="get_telemetry",
            params={},
            started_at=started_at,
            result=result,
            telemetry_before=telemetry_before,
        )
        return result

    @mcp.tool(
        title="Queue Control",
        description=(
            "Inspect or manage the server-side command queue. "
            "action='status' returns current depth and worker state; "
            "action='clear' cancels all pending (not yet executing) commands."
        ),
        annotations=ToolAnnotations(title="Queue Control", readOnlyHint=False),
    )
    async def queue_control(action: str = "status") -> CommandResult:
        if action == "status":
            return CommandResult.ok("Queue status retrieved.", data=command_queue.status())
        if action == "clear":
            result = await command_queue.stop_and_clear()
            return CommandResult.ok(
                f"Queue cleared: {result['cleared_count']} command(s) cancelled.",
                data=result,
            )
        return CommandResult.fail(
            f"Unknown action '{action}'. Use 'status' or 'clear'.",
            ErrorCode.INVALID_PARAMS,
        )

    @mcp.resource(
        "uav://status/state",
        title="Vehicle State",
        description="Authoritative high-level state of the vehicle.",
    )
    def status_state() -> str:
        return current_snapshot().state.value

    @mcp.resource(
        "uav://telemetry/snapshot",
        title="Telemetry Snapshot",
        description="Structured live telemetry snapshot for model consumption.",
    )
    def telemetry_snapshot() -> TelemetrySnapshot:
        return current_snapshot()

    @mcp.resource(
        "uav://runtime/health",
        title="Runtime Health",
        description="Read-only runtime stack, simulator, camera, gimbal, and readiness summary.",
    )
    def runtime_health() -> dict[str, object]:
        return _dashboard_runtime_health()

    @mcp.resource(
        "uav://evaluation/summary",
        title="Evaluation Summary",
        description="Read-only summary of the latest benchmark artifacts under evaluation/results.",
    )
    def evaluation_summary() -> dict[str, object]:
        return _dashboard_evaluation_summary()

    @mcp.resource(
        "uav://config/safety",
        title="Safety Configuration",
        description=(
            "Runtime safety bounds, assistant settings, and manual-control capability "
            "flags."
        ),
    )
    def safety_config() -> dict[str, object]:
        settings = resolved_services.settings
        return {
            "geofence_center_lat": settings.geofence_center_lat,
            "geofence_center_lon": settings.geofence_center_lon,
            "geofence_radius_m": settings.geofence_radius_m,
            "px4_home_lat": settings.px4_home_lat,
            "px4_home_lon": settings.px4_home_lon,
            "min_altitude_m": settings.min_altitude_m,
            "max_altitude_m": settings.max_altitude_m,
            "max_speed_m_s": settings.max_speed_m_s,
            "max_relative_move_distance_m": settings.max_relative_move_distance_m,
            "min_orbit_radius_m": settings.min_orbit_radius_m,
            "max_orbit_radius_m": settings.max_orbit_radius_m,
            "default_takeoff_altitude_m": settings.default_takeoff_altitude_m,
            "default_mission_speed_m_s": settings.default_mission_speed_m_s,
            "command_rate_limit_per_sec": settings.command_rate_limit_per_sec,
            "min_battery_percent": settings.min_battery_percent,
            "assistant_enabled": settings.assistant_enabled,
            "assistant_model": settings.assistant_model,
            "assistant_preview_default": settings.assistant_preview_default,
            "assistant_bypass_available": settings.assistant_bypass_available,
            "assistant_vision_enabled": settings.assistant_vision_enabled,
            "manual_control": {
                "translation_step_m": settings.manual_control_translation_step_m,
                "altitude_step_m": settings.manual_control_altitude_step_m,
                "yaw_step_deg": settings.manual_control_yaw_step_deg,
                "gimbal_pitch_step_deg": settings.manual_control_gimbal_pitch_step_deg,
                "supports_translation": settings.manual_control_supports_translation,
                "supports_altitude": settings.manual_control_supports_altitude,
                "supports_yaw": settings.manual_control_supports_yaw,
                "supports_gimbal_pitch": settings.manual_control_supports_gimbal_pitch,
            },
            "camera_enabled": settings.camera_enabled,
            "camera_ros_topic": settings.camera_ros_topic,
            "camera_fps": settings.camera_fps,
        }

    @mcp.resource(
        "uav://guide/workflows",
        title="Workflow Guide",
        description="Short guidance for AI clients choosing between launch, move, orbit, recovery, and manual-framing workflows.",
    )
    def workflow_guide() -> str:
        return workflow_guide_text(resolved_services.settings)

    @mcp.prompt(
        title="Operator Workflow Brief",
        description=(
            "Concise operator guidance for AI clients: prefer guided_takeoff, keep "
            "raw takeoff low-level, and use airframe yaw plus gimbal pitch for framing."
        ),
    )
    def operator_workflow_brief() -> list[PromptMessage]:
        return [
            PromptMessage(
                role="user",
                content=TextContent(
                    type="text",
                    text=(
                        "Workflow brief:\n"
                        "- Use guided_takeoff for requests like 'take off 50m'. It "
                        "will connect and arm if needed before takeoff.\n"
                        "- Use takeoff only when the vehicle is already armed and a "
                        "low-level launch is explicitly intended.\n"
                        "- Use yaw_relative and gimbal_pitch_relative for framing and "
                        "operator adjustments when supported.\n"
                        "- Use hold, rtl, and land for recovery.\n"
                        "- Do not invent unsupported actions."
                    ),
                ),
            )
        ]

    # --- Dashboard wiring ---
    _tool_dispatch: dict[str, Any] = {
        "connect": connect,
        "guided_takeoff": guided_takeoff,
        "arm": arm,
        "disarm": disarm,
        "takeoff": takeoff,
        "land": land,
        "hold": hold,
        "rtl": rtl,
        "goto_relative": goto_relative,
        "yaw_relative": yaw_relative,
        "gimbal_pitch_relative": gimbal_pitch_relative,
        "orbit": orbit,
        "get_status": get_status,
        "get_telemetry": get_telemetry,
        "queue_control": queue_control,
    }

    async def _dashboard_validate_and_run(command_name: str, params: dict[str, Any]) -> CommandResult:
        handler = _tool_dispatch.get(command_name)
        if handler is None:
            return CommandResult.fail(
                f"Unknown command: {command_name}",
                ErrorCode.INVALID_PARAMS,
            )
        try:
            if command_name == "orbit" and isinstance(params.get("yaw_behavior"), str):
                params = {
                    **params,
                    "yaw_behavior": OrbitYawBehavior.parse(params["yaw_behavior"]),
                }
            result = await handler(**params)
        except TypeError as exc:
            return CommandResult.fail(
                f"Invalid parameters for '{command_name}': {exc}",
                ErrorCode.INVALID_PARAMS,
            )
        except ValueError as exc:
            return CommandResult.fail(
                f"Invalid parameters for '{command_name}': {exc}",
                ErrorCode.INVALID_PARAMS,
            )
        if isinstance(result, CommandResult):
            return result
        # get_telemetry returns TelemetrySnapshot
        return CommandResult.ok("Telemetry retrieved.", data=result.model_dump(mode="json"))

    def _dashboard_config() -> dict[str, Any]:
        settings = resolved_services.settings
        return {
            "geofence_center_lat": settings.geofence_center_lat,
            "geofence_center_lon": settings.geofence_center_lon,
            "geofence_radius_m": settings.geofence_radius_m,
            "px4_home_lat": settings.px4_home_lat,
            "px4_home_lon": settings.px4_home_lon,
            "min_altitude_m": settings.min_altitude_m,
            "max_altitude_m": settings.max_altitude_m,
            "max_speed_m_s": settings.max_speed_m_s,
            "min_orbit_radius_m": settings.min_orbit_radius_m,
            "max_orbit_radius_m": settings.max_orbit_radius_m,
            "default_takeoff_altitude_m": settings.default_takeoff_altitude_m,
            "default_mission_speed_m_s": settings.default_mission_speed_m_s,
            "assistant_enabled": settings.assistant_enabled,
            "assistant_model": settings.assistant_model,
            "assistant_preview_default": settings.assistant_preview_default,
            "assistant_bypass_available": settings.assistant_bypass_available,
            "assistant_vision_enabled": settings.assistant_vision_enabled,
            "assistant": {
                "enabled": settings.assistant_enabled,
                "default_mode": "gemini" if assistant.api_available else "fallback",
                "preview_default": settings.assistant_preview_default,
                "bypass_available": settings.assistant_bypass_available,
                "vision_enabled": settings.assistant_vision_enabled,
                "fallback_available": True,
            },
            "camera": {
                **_camera_status_dict(),
                "stabilized": settings.camera_stabilized,
                "params": camera_params.to_dict(),
                "stream_url": "/dashboard/api/camera/stream",
            },
            "manual_control": {
                "translation_step_m": settings.manual_control_translation_step_m,
                "altitude_step_m": settings.manual_control_altitude_step_m,
                "yaw_step_deg": settings.manual_control_yaw_step_deg,
                "gimbal_pitch_step_deg": settings.manual_control_gimbal_pitch_step_deg,
                "supports_translation": settings.manual_control_supports_translation,
                "supports_altitude": settings.manual_control_supports_altitude,
                "supports_yaw": settings.manual_control_supports_yaw,
                "supports_gimbal_pitch": settings.manual_control_supports_gimbal_pitch,
            },
            "monitoring": {
                "runtime_health_url": "/dashboard/api/runtime-health",
                "evaluation_summary_url": "/dashboard/api/evaluation-summary",
            },
        }

    async def _dashboard_project_pixel(params: dict[str, Any]) -> dict[str, Any]:
        try:
            u = float(params["u"])
            v = float(params["v"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Projection requires numeric 'u' and 'v' pixel coordinates.") from exc
        raw_gimbal_pitch_deg = resolved_services.controller.current_gimbal_pitch_deg()
        # ``current_gimbal_yaw_deg`` is the value the projection trusts — for
        # the gz_x500_gimbal setup it's hard-zeroed because we don't command
        # yaw. ``observed_gimbal_yaw_deg`` is the live MAVSDK reading,
        # surfaced only for the diagnostic block in the response so the
        # operator can see whether the joint is drifting.
        gimbal_yaw_deg = resolved_services.controller.current_gimbal_yaw_deg()
        observed_gimbal_yaw_deg = resolved_services.controller.observed_gimbal_yaw_deg()
        pose = current_drone_pose()

        # Normalise gimbal pitch sign so positive=up matches the projection
        # rotation convention. Configurable for firmwares that report the
        # opposite sign.
        gimbal_pitch_deg = raw_gimbal_pitch_deg * resolved_services.settings.camera_gimbal_pitch_sign

        # If the autopilot reports gimbal yaw in earth/NED frame, subtract
        # the vehicle heading to recover the vehicle-frame gimbal yaw the
        # projection math expects. Only meaningful when the project trusts
        # the live gimbal yaw value — in this codebase yaw is locked to 0,
        # but the knob is preserved for future setups that do command yaw.
        if resolved_services.settings.camera_gimbal_yaw_frame == "earth":
            gimbal_yaw_deg = gimbal_yaw_deg - pose.yaw_deg

        effective_params = CameraParams(
            width_px=camera_params.width_px,
            height_px=camera_params.height_px,
            hfov_rad=camera_params.hfov_rad,
            focal_length_px=camera_params.focal_length_px,
            mount_yaw_deg=camera_params.mount_yaw_deg + gimbal_yaw_deg,
            mount_pitch_deg=camera_params.mount_pitch_deg + gimbal_pitch_deg,
            mount_roll_deg=camera_params.mount_roll_deg,
            principal_x_px=camera_params.principal_x_px,
            principal_y_px=camera_params.principal_y_px,
        )
        projected_point = pixel_to_world(
            u,
            v,
            effective_params,
            pose,
            terrain=terrain_sampler,
            origin_lat_deg=resolved_services.settings.geofence_center_lat,
            origin_lon_deg=resolved_services.settings.geofence_center_lon,
        )
        projection: dict[str, Any] = projected_point.to_dict()
        projection["pixel"] = {"u": u, "v": v}
        projection["selection_anchor"] = str(params.get("selection_anchor") or "pixel")
        projection["terrain_aware"] = terrain_sampler is not None
        projection["camera"] = {
            "base": camera_params.to_dict(),
            "effective": effective_params.to_dict(),
            "stabilized": resolved_services.settings.camera_stabilized,
        }
        projection["gimbal"] = {
            "tracked_pitch_deg": gimbal_pitch_deg,
            "tracked_yaw_deg": gimbal_yaw_deg,
            "raw_pitch_deg": raw_gimbal_pitch_deg,
            "raw_yaw_deg": observed_gimbal_yaw_deg,
            "yaw_frame": resolved_services.settings.camera_gimbal_yaw_frame,
            "pitch_sign": resolved_services.settings.camera_gimbal_pitch_sign,
            "yaw_locked_forward": True,
        }
        # Debug-level projection trace. Operator can `LOG_LEVEL=DEBUG` and
        # tail the launcher log to verify which intermediate value drifts when
        # calibrating mount offsets / gimbal frame.
        import logging as _log
        _log.getLogger(__name__).debug(
            "project_pixel u=%.1f v=%.1f drone_yaw=%.2f observed_gimbal_yaw=%s "
            "applied_gimbal_yaw=%.2f raw_gimbal_pitch=%.2f applied_pitch=%.2f "
            "mount_yaw=%.2f → lat=%.6f lon=%.6f dist=%.1f terrain=%s",
            u, v, pose.yaw_deg,
            f"{observed_gimbal_yaw_deg:.2f}" if observed_gimbal_yaw_deg is not None else "none",
            gimbal_yaw_deg,
            raw_gimbal_pitch_deg, gimbal_pitch_deg, camera_params.mount_yaw_deg,
            projected_point.latitude_deg, projected_point.longitude_deg,
            projected_point.distance_m, projected_point.terrain_used,
        )
        projection["pose"] = {
            "latitude_deg": pose.lat_deg,
            "longitude_deg": pose.lon_deg,
            "absolute_altitude_m": pose.absolute_altitude_m,
            "relative_altitude_m": pose.relative_altitude_m,
            "home_absolute_altitude_m": pose.home_absolute_altitude_m,
            "yaw_deg": pose.yaw_deg,
            "pitch_deg": pose.pitch_deg,
            "roll_deg": pose.roll_deg,
        }
        return projection

    async def _dashboard_select_and_orbit(params: dict[str, Any]) -> CommandResult:
        try:
            projection = await _dashboard_project_pixel(params)
            radius_m = float(params.get("radius_m", 12.0))
            velocity_m_s = float(
                params.get(
                    "velocity_m_s",
                    min(resolved_services.settings.default_mission_speed_m_s, 3.0),
                )
            )
            requested_yaw_behavior = OrbitYawBehavior.parse(
                params.get(
                    "yaw_behavior",
                    OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER.value,
                )
            )
        except ValueError as exc:
            return CommandResult.fail(str(exc), ErrorCode.INVALID_PARAMS)
        except RuntimeError as exc:
            return CommandResult.fail(str(exc), ErrorCode.PREFLIGHT_FAILED)

        violation, resolved = _resolve_target_orbit(
            target_latitude_deg=projection["latitude_deg"],
            target_longitude_deg=projection["longitude_deg"],
            requested_radius_m=radius_m,
            requested_velocity_m_s=velocity_m_s,
            requested_absolute_altitude_m=(
                float(params["absolute_altitude_m"]) if "absolute_altitude_m" in params else None
            ),
        )
        if violation is not None:
            return violation

        yaw_behavior, framing = await _resolve_orbit_framing(
            target_latitude_deg=projection["latitude_deg"],
            target_longitude_deg=projection["longitude_deg"],
            target_absolute_altitude_m=projection["absolute_altitude_m"],
            requested_yaw_behavior=requested_yaw_behavior,
            explicit_yaw_behavior="yaw_behavior" in params,
        )
        result = await _dashboard_validate_and_run(
            "orbit",
            {
                "latitude_deg": projection["latitude_deg"],
                "longitude_deg": projection["longitude_deg"],
                "absolute_altitude_m": resolved["absolute_altitude_m"],
                "radius_m": resolved["resolved_radius_m"],
                "velocity_m_s": resolved["velocity_m_s"],
                "yaw_behavior": yaw_behavior,
            },
        )
        if result.data is None:
            result.data = {}
        result.data["projection"] = projection
        result.data["selection"] = {
            "u": float(params["u"]),
            "v": float(params["v"]),
            "selection_anchor": projection.get("selection_anchor"),
        }
        result.data["orbit_resolution"] = resolved
        result.data["framing"] = framing
        return result

    async def _best_effort_point_roi(
        latitude_deg: float,
        longitude_deg: float,
        target_absolute_altitude_m: float,
    ) -> dict[str, Any]:
        roi_result = await resolved_services.controller.point_gimbal_at(
            latitude_deg,
            longitude_deg,
            target_absolute_altitude_m,
        )
        _record_gimbal_result(roi_result, source="roi")
        return {
            "attempted": True,
            "success": roi_result.success,
            "message": roi_result.message,
            "error_code": roi_result.error_code.value if roi_result.error_code is not None else None,
        }

    def _normalize_heading_deg(yaw_deg: float) -> float:
        return ((yaw_deg + 180.0) % 360.0) - 180.0

    def _target_bearing_context(
        target_latitude_deg: float,
        target_longitude_deg: float,
    ) -> dict[str, Any]:
        snapshot = current_snapshot()
        if snapshot.latitude_deg is None or snapshot.longitude_deg is None:
            return {}
        north_m, east_m = coordinate_offset_m(
            snapshot.latitude_deg,
            snapshot.longitude_deg,
            target_latitude_deg,
            target_longitude_deg,
        )
        bearing_deg = degrees(atan2(east_m, north_m))
        current_yaw_deg = snapshot.yaw_deg if snapshot.yaw_deg is not None else 0.0
        return {
            "target_bearing_deg": round(_normalize_heading_deg(bearing_deg), 1),
            "current_yaw_deg": round(current_yaw_deg, 1),
            "heading_error_deg": round(
                _normalize_heading_deg(bearing_deg - current_yaw_deg),
                1,
            ),
        }

    def _resolve_roi_target_absolute_altitude_m(
        *,
        selected_target: dict[str, Any] | None = None,
        fallback_absolute_altitude_m: float,
    ) -> float:
        if isinstance(selected_target, dict):
            raw_absolute_altitude_m = selected_target.get("absolute_altitude_m")
            if raw_absolute_altitude_m is not None:
                try:
                    return float(raw_absolute_altitude_m)
                except (TypeError, ValueError):
                    pass

        inferred_ground_altitude_m = current_snapshot().inferred_home_absolute_altitude_m()
        if inferred_ground_altitude_m is not None:
            return inferred_ground_altitude_m
        return fallback_absolute_altitude_m

    async def _resolve_orbit_framing(
        *,
        target_latitude_deg: float,
        target_longitude_deg: float,
        target_absolute_altitude_m: float,
        requested_yaw_behavior: OrbitYawBehavior,
        explicit_yaw_behavior: bool,
    ) -> tuple[OrbitYawBehavior, dict[str, Any]]:
        resolved_yaw_behavior = requested_yaw_behavior
        framing_mode = "airframe_center"
        roi_status = {
            "attempted": False,
            "success": False,
            "message": "ROI not used; airframe yaw is responsible for orbit framing.",
            "error_code": None,
        }
        if explicit_yaw_behavior and requested_yaw_behavior is OrbitYawBehavior.HOLD_INITIAL_HEADING:
            roi_status = await _best_effort_point_roi(
                target_latitude_deg,
                target_longitude_deg,
                target_absolute_altitude_m,
            )
            framing_mode = "gimbal_roi"
        return resolved_yaw_behavior, {
            "framing_mode": framing_mode,
            "requested_yaw_behavior": requested_yaw_behavior.value,
            "resolved_yaw_behavior": resolved_yaw_behavior.value,
            "target_absolute_altitude_m": target_absolute_altitude_m,
            "roi": roi_status,
            **_target_bearing_context(target_latitude_deg, target_longitude_deg),
        }

    def _resolve_target_orbit(
        *,
        target_latitude_deg: float,
        target_longitude_deg: float,
        requested_radius_m: float,
        requested_velocity_m_s: float,
        requested_absolute_altitude_m: float | None,
    ) -> tuple[CommandResult | None, dict[str, Any]]:
        snapshot = current_snapshot()
        if snapshot.absolute_altitude_m is None:
            return (
                CommandResult.fail(
                    "Current altitude is unavailable; orbit target altitude cannot be resolved.",
                    ErrorCode.CONNECTION_LOST,
                ),
                {},
            )
        resolved_absolute_altitude_m = (
            requested_absolute_altitude_m
            if requested_absolute_altitude_m is not None
            else snapshot.absolute_altitude_m
        )
        geometry: dict[str, Any] = {
            "requested_radius_m": requested_radius_m,
            "resolved_radius_m": requested_radius_m,
        }
        if snapshot.latitude_deg is None or snapshot.longitude_deg is None:
            return None, {
                **geometry,
                "absolute_altitude_m": resolved_absolute_altitude_m,
                "velocity_m_s": requested_velocity_m_s,
            }
        current_distance_m = haversine_distance_m(
            snapshot.latitude_deg,
            snapshot.longitude_deg,
            target_latitude_deg,
            target_longitude_deg,
        )
        geometry["current_target_distance_m"] = round(current_distance_m, 2)
        if current_distance_m < resolved_services.settings.min_orbit_radius_m:
            return (
                CommandResult.fail(
                    "Target is too close beneath the aircraft for a stable orbit start. Reposition first or widen the standoff before orbiting.",
                    ErrorCode.INVALID_PARAMS,
                    data={
                        "current_target_distance_m": round(current_distance_m, 2),
                        "minimum_start_distance_m": resolved_services.settings.min_orbit_radius_m,
                    },
                ),
                geometry,
            )
        resolved_radius_m = max(requested_radius_m, current_distance_m)
        return None, {
            **geometry,
            "resolved_radius_m": round(resolved_radius_m, 2),
            "absolute_altitude_m": resolved_absolute_altitude_m,
            "velocity_m_s": requested_velocity_m_s,
        }

    async def _dashboard_select_and_approach(params: dict[str, Any]) -> CommandResult:
        try:
            projection = await _dashboard_project_pixel(params)
            snapshot = current_snapshot()
            if snapshot.latitude_deg is None or snapshot.longitude_deg is None:
                return CommandResult.fail(
                    "Current position is unavailable; cannot compute an approach vector.",
                    ErrorCode.CONNECTION_LOST,
                )
            target_altitude_m = float(
                params.get(
                    "altitude_m",
                    snapshot.relative_altitude_m or resolved_services.settings.default_takeoff_altitude_m,
                )
            )
            north_m, east_m = coordinate_offset_m(
                snapshot.latitude_deg,
                snapshot.longitude_deg,
                projection["latitude_deg"],
                projection["longitude_deg"],
            )
        except ValueError as exc:
            return CommandResult.fail(str(exc), ErrorCode.INVALID_PARAMS)
        except RuntimeError as exc:
            return CommandResult.fail(str(exc), ErrorCode.PREFLIGHT_FAILED)

        result = await _dashboard_validate_and_run(
            "goto_relative",
            {
                "north_m": north_m,
                "east_m": east_m,
                "altitude_m": target_altitude_m,
            },
        )
        if result.data is None:
            result.data = {}
        result.data["projection"] = projection
        result.data["selection"] = {
            "u": float(params["u"]),
            "v": float(params["v"]),
            "selection_anchor": projection.get("selection_anchor"),
        }
        return result

    async def _resolve_assistant_camera_target(
        operator_text: str,
        selected_target: AssistantTarget | None,
    ) -> tuple[AssistantTarget | None, dict[str, Any] | None, str | None]:
        if not needs_camera_target_resolution(operator_text, selected_target=selected_target):
            return selected_target, None, None

        frame = camera_streamer.get_frame()
        if frame is None:
            status = camera_streamer.status().to_dict()
            reason = status.get("reason") or "No camera frame is available for assistant vision."
            return selected_target, {"status": status}, reason

        try:
            visual_target = await asyncio.wait_for(
                assistant.locate_camera_target(
                    operator_text,
                    image_jpeg=frame,
                    image_width_px=camera_params.width_px,
                    image_height_px=camera_params.height_px,
                ),
                timeout=8.0,
            )
        except Exception as exc:
            return selected_target, None, str(exc)

        vision_dict = visual_target.model_dump(mode="json")
        if not visual_target.found or visual_target.u is None or visual_target.v is None:
            reason = visual_target.rationale or "Assistant vision could not identify a unique target."
            return selected_target, {"vision": vision_dict}, reason

        try:
            projection = await _dashboard_project_pixel(
                {
                    "u": visual_target.u,
                    "v": visual_target.v,
                    "selection_anchor": visual_target.selection_anchor,
                }
            )
        except (ValueError, RuntimeError) as exc:
            return selected_target, {"vision": vision_dict}, str(exc)

        # End-to-end diagnostic so a regression in either Gemini accuracy
        # or the projection pipeline can be told apart from the log.
        import logging as _log
        _bearing_from_drone = degrees(
            atan2(float(projection["east_m"]), float(projection["north_m"]))
        )
        _log.getLogger(__name__).info(
            "assistant_vision: %r → pixel=(%.1f, %.1f) anchor=%s → "
            "lat=%.6f lon=%.6f dist=%.1fm bearing≈%.1f° from drone",
            (visual_target.label or "?"),
            visual_target.u, visual_target.v,
            visual_target.selection_anchor,
            float(projection["latitude_deg"]),
            float(projection["longitude_deg"]),
            float(projection["distance_m"]),
            _bearing_from_drone,
        )

        resolved_target = AssistantTarget(
            source="camera_vision",
            latitude_deg=float(projection["latitude_deg"]),
            longitude_deg=float(projection["longitude_deg"]),
            absolute_altitude_m=float(projection["absolute_altitude_m"]),
            north_m=float(projection["north_m"]),
            east_m=float(projection["east_m"]),
            distance_m=float(projection["distance_m"]),
            label=visual_target.label or "Camera target",
        )
        return (
            resolved_target,
            {
                "vision": vision_dict,
                "projection": projection,
                "target": resolved_target.model_dump(mode="json"),
            },
            None,
        )

    async def _dashboard_assistant_plan(params: dict[str, Any]) -> dict[str, Any]:
        operator_text = str(params.get("text", "")).strip()
        selected_target = None
        if isinstance(params.get("selected_target"), dict):
            try:
                selected_target = AssistantTarget.model_validate(params["selected_target"])
            except Exception:
                selected_target = None
                
        started_at = monotonic()
        telemetry_before = current_snapshot()
        visual_resolution: dict[str, Any] | None = None
        visual_reason: str | None = None
        selected_target, visual_resolution, visual_reason = await _resolve_assistant_camera_target(
            operator_text,
            selected_target,
        )
        
        plan = await assistant.plan(
            operator_text,
            telemetry=telemetry_before,
            selected_target=selected_target,
            grounding=await _assistant_grounding(),
        )
        
        duration_ms = round((monotonic() - started_at) * 1000.0, 3)
        result_dict = {
            "source": plan.source,
            "operator_text": plan.operator_text,
            "assistant_text": plan.assistant_text,
            "requires_confirmation": plan.requires_confirmation,
            "proposed_calls": [
                {
                    "command": call.name,
                    "body": call.arguments,
                    "summary": call.summary,
                }
                for call in plan.proposed_calls
            ],
            "selected_target": selected_target.model_dump(mode="json") if selected_target else None,
            "fallback_reason": plan.fallback_reason,
            "visual_target": visual_resolution,
        }
        if visual_reason is not None:
            result_dict["visual_target_error"] = visual_reason
            if not result_dict["fallback_reason"]:
                result_dict["fallback_reason"] = visual_reason
            if not plan.proposed_calls and needs_camera_target_resolution(
                operator_text,
                selected_target=selected_target,
            ):
                result_dict["assistant_text"] = (
                    "I could not resolve the requested camera target: "
                    f"{visual_reason}"
                )
        
        observability.record_event(
            ObservabilityEvent(
                timestamp=now_iso(),
                source="assistant",
                action="plan",
                command="plan",
                success=plan.fallback_reason is None,
                duration_ms=duration_ms,
                message=plan.assistant_text,
                request={"operator_text": operator_text},
                response=result_dict,
                telemetry_before=telemetry_before.model_dump(mode="json"),
                telemetry_after=current_snapshot().model_dump(mode="json"),
            )
        )
        
        return result_dict

    async def _dashboard_assistant_execute(params: dict[str, Any]) -> dict[str, Any]:
        operator_text = str(params.get("text", "")).strip()
        assistant_text = str(params.get("assistant_text") or "Executing proposed calls.")
        source = str(params.get("source") or ("gemini" if assistant.api_available else "fallback"))
        proposed_calls = params.get("proposed_calls")
        planned_selected_target = (
            params.get("selected_target") if isinstance(params.get("selected_target"), dict) else None
        )
        planned_visual_target = None
        if not isinstance(proposed_calls, list) or not proposed_calls:
            plan_result = await _dashboard_assistant_plan(params)
            assistant_text = str(plan_result.get("assistant_text") or assistant_text)
            source = str(plan_result.get("source") or source)
            proposed_calls = list(plan_result.get("proposed_calls") or [])
            planned_selected_target = (
                plan_result.get("selected_target")
                if isinstance(plan_result.get("selected_target"), dict)
                else planned_selected_target
            )
            planned_visual_target = plan_result.get("visual_target")
        executed_calls: list[dict[str, Any]] = []
        overall_success = True
        for raw_call in proposed_calls[:4]:
            command_name = str(raw_call.get("command", "")).strip()
            payload = raw_call.get("body") if isinstance(raw_call.get("body"), dict) else {}
            if command_name not in ASSISTANT_ALLOWED_COMMANDS:
                result = CommandResult.fail(
                    f"Assistant command '{command_name}' is not allowed.",
                    ErrorCode.INVALID_PARAMS,
                )
            else:
                result = await _dashboard_validate_and_run(command_name, payload)
            executed_calls.append(
                {
                    "command": command_name,
                    "body": payload,
                    "success": result.success,
                    "message": result.message,
                    "error_code": result.error_code.value if result.error_code is not None else None,
                    "data": result.data,
                }
            )
            if not result.success:
                overall_success = False
                break
        return {
            "source": source,
            "operator_text": operator_text,
            "assistant_text": assistant_text,
            "executed_calls": executed_calls,
            "success": overall_success,
            "selected_target": planned_selected_target,
            "visual_target": planned_visual_target,
        }

    async def _dashboard_target_orbit(params: dict[str, Any]) -> CommandResult:
        selected_target = params.get("selected_target")
        if not isinstance(selected_target, dict):
            return CommandResult.fail(
                "No map target is selected.",
                ErrorCode.INVALID_PARAMS,
            )
        try:
            target_latitude_deg = float(selected_target["latitude_deg"])
            target_longitude_deg = float(selected_target["longitude_deg"])
            requested_radius_m = float(params.get("radius_m", 12.0))
            requested_velocity_m_s = float(
                params.get(
                    "velocity_m_s",
                    min(resolved_services.settings.default_mission_speed_m_s, 3.0),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            return CommandResult.fail(str(exc), ErrorCode.INVALID_PARAMS)

        violation, resolved = _resolve_target_orbit(
            target_latitude_deg=target_latitude_deg,
            target_longitude_deg=target_longitude_deg,
            requested_radius_m=requested_radius_m,
            requested_velocity_m_s=requested_velocity_m_s,
            requested_absolute_altitude_m=(
                float(params["absolute_altitude_m"]) if "absolute_altitude_m" in params else None
            ),
        )
        if violation is not None:
            return violation

        try:
            requested_yaw_behavior = OrbitYawBehavior.parse(
                params.get(
                    "yaw_behavior",
                    OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER.value,
                )
            )
        except ValueError as exc:
            return CommandResult.fail(str(exc), ErrorCode.INVALID_PARAMS)
        yaw_behavior, framing = await _resolve_orbit_framing(
            target_latitude_deg=target_latitude_deg,
            target_longitude_deg=target_longitude_deg,
            target_absolute_altitude_m=_resolve_roi_target_absolute_altitude_m(
                selected_target=selected_target,
                fallback_absolute_altitude_m=resolved["absolute_altitude_m"],
            ),
            requested_yaw_behavior=requested_yaw_behavior,
            explicit_yaw_behavior="yaw_behavior" in params,
        )
        result = await _dashboard_validate_and_run(
            "orbit",
            {
                "latitude_deg": target_latitude_deg,
                "longitude_deg": target_longitude_deg,
                "absolute_altitude_m": resolved["absolute_altitude_m"],
                "radius_m": resolved["resolved_radius_m"],
                "velocity_m_s": resolved["velocity_m_s"],
                "yaw_behavior": yaw_behavior,
            },
        )
        if result.data is None:
            result.data = {}
        result.data["target"] = selected_target
        result.data["orbit_resolution"] = resolved
        result.data["framing"] = framing
        return result

    async def _dashboard_manual_move(params: dict[str, Any]) -> CommandResult:
        try:
            north_m = float(params.get("north_m", 0.0))
            east_m = float(params.get("east_m", 0.0))
            altitude_m = float(params["altitude_m"])
        except (KeyError, TypeError, ValueError) as exc:
            return CommandResult.fail(
                f"Manual move requires numeric north_m, east_m, and altitude_m values: {exc}",
                ErrorCode.INVALID_PARAMS,
            )
        manual_rate_violation = _check_manual_rate()
        if manual_rate_violation is not None:
            return manual_rate_violation
        return await _observed_command(
            "goto_relative",
            params,
            lambda: resolved_services.controller.goto_relative(north_m, east_m, altitude_m),
            source="manual",
            validate_params={"north_m": north_m, "east_m": east_m, "altitude_m": altitude_m, "enforce_rate_limit": False},
        )

    async def _dashboard_manual_yaw(params: dict[str, Any]) -> CommandResult:
        try:
            delta_deg = float(params["delta_deg"])
        except (KeyError, TypeError, ValueError) as exc:
            return CommandResult.fail(
                f"Manual yaw requires a numeric delta_deg value: {exc}",
                ErrorCode.INVALID_PARAMS,
            )
        manual_rate_violation = _check_manual_rate()
        if manual_rate_violation is not None:
            return manual_rate_violation
        return await _observed_command(
            "yaw_relative",
            params,
            lambda: resolved_services.controller.yaw_relative(delta_deg),
            source="manual",
            validate_params={"delta_deg": delta_deg, "enforce_rate_limit": False},
        )

    async def _dashboard_manual_gimbal_pitch(params: dict[str, Any]) -> CommandResult:
        try:
            delta_deg = float(params["delta_deg"])
        except (KeyError, TypeError, ValueError) as exc:
            return CommandResult.fail(
                f"Manual gimbal pitch requires a numeric delta_deg value: {exc}",
                ErrorCode.INVALID_PARAMS,
            )
        manual_rate_violation = _check_manual_rate()
        if manual_rate_violation is not None:
            return manual_rate_violation
        async def _gimbal_runner() -> CommandResult:
            result = await resolved_services.controller.gimbal_pitch_relative(delta_deg)
            _record_gimbal_result(result, source="manual")
            return result

        return await _observed_command(
            "gimbal_pitch_relative",
            params,
            _gimbal_runner,
            source="manual",
            validate_params={"delta_deg": delta_deg, "enforce_rate_limit": False},
        )

    dashboard_state = DashboardState(
        get_snapshot=current_snapshot,
        validate_and_run=_dashboard_validate_and_run,
        get_config=_dashboard_config,
        get_runtime_health=_dashboard_runtime_health,
        get_evaluation_summary=_dashboard_evaluation_summary,
        observability=observability,
        assistant_plan=_dashboard_assistant_plan,
        assistant_execute=_dashboard_assistant_execute,
        project_pixel=_dashboard_project_pixel,
        select_and_orbit=_dashboard_select_and_orbit,
        select_and_approach=_dashboard_select_and_approach,
        manual_move=_dashboard_manual_move,
        manual_yaw=_dashboard_manual_yaw,
        manual_gimbal_pitch=_dashboard_manual_gimbal_pitch,
        target_orbit=_dashboard_target_orbit,
        camera_streamer=camera_streamer,
        queue_status=command_queue.status,
        queue_clear=command_queue.stop_and_clear,
    )
    register_dashboard_routes(mcp, dashboard_state)

    return mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe UAV MCP server")
    parser.add_argument(
        "--backend",
        default=None,
        choices=("live", "local"),
        help="Backend mode. Use 'local' for API-level testing without PX4 SITL.",
    )
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=("stdio", "streamable-http", "http"),
        help="Transport mode for the FastMCP server.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host.")
    parser.add_argument("--port", default=8000, type=int, help="HTTP bind port.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    transport = "streamable-http" if args.transport == "http" else args.transport
    settings = Settings(backend_mode=args.backend) if args.backend is not None else get_settings()
    server = create_server(build_services(settings=settings), host=args.host, port=args.port)
    server.run(transport=transport)
