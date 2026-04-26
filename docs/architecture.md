# Architecture

## Goal

The system exposes safe, bounded UAV control functions through MCP while keeping the actual flight stabilization and low-level control inside PX4.

## Core layers

1. MCP server and dashboard routes
2. Safety and validation layer
3. Drone control layer built on a testable backend boundary
4. MAVSDK adapter
5. Optional dashboard helpers: camera ingestion and projection math
6. PX4 SITL + Gazebo

## Main data flow

```text
LLM / MCP client
    -> MCP tool call
    -> server.py
    -> safety.py
    -> drone.py / mission.py
    -> MAVSDK
    -> PX4 SITL
    -> telemetry.py
    -> MCP response
```

## Telemetry data flow

MAVSDK provides telemetry as async subscriptions (position, battery, flight mode, etc.). The telemetry manager subscribes to these streams and caches the latest values into a `TelemetrySnapshot`. MCP tools poll the cached snapshot on demand.

```text
PX4 SITL
    -> MAVSDK async subscriptions
    -> TelemetryManager._update() (caches latest values)
    -> TelemetrySnapshot (in-memory)
    -> polled by get_telemetry / get_status tools
```

Future iteration: expose telemetry as an MCP Resource with subscription support so clients receive push updates instead of polling.

## Current implementation notes

- `server.py` wires the FastMCP tool surface and read-only resources
- `dashboard.py` and `dashboard_ui.py` provide the operator web surface on the same process and port
- `observability.py` and `observability_ui.py` provide a read-only thesis analysis surface for latency, reliability, safety, runtime context, and benchmark artifacts
- `safety.py` owns state, preflight, bounds, geofence, and rate-limit checks
- `drone.py` keeps the control path testable by depending on a backend protocol instead of directly on MAVSDK objects and now includes orbit dispatch
- `telemetry.py` owns the in-memory `TelemetrySnapshot` cache and telemetry subscriptions, including attitude
- `camera.py` optionally bridges ROS2 image messages into MJPEG for the dashboard
- `projection.py` handles pixel-to-world coordinate projection for target selection workflows

## Core scope

- connect
- arm
- disarm when safe
- takeoff
- land
- return-to-launch
- bounded point-to-point movement
- bounded orbit around a selected or specified point
- waypoint mission execution
- telemetry and status
- operator web UI with telemetry, event log, live map, camera feed, target selection, and browser voice control
- observability page with benchmark artifact exploration, latency percentiles, safety rejection analysis, runtime context, and JSON export

## Deferred scope

- gimbal control
- semantic object detection
- terrain-aware or 3D projection beyond the flat-ground assumption
