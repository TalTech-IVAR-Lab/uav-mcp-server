# UAV MCP Server

This repository contains a simulation-first UAV control middleware for a thesis project built around the Model Context Protocol (MCP). The target system connects an AI agent to a PX4-based UAV running in Software-In-The-Loop (SITL), with a safety layer between the MCP tool surface and the flight controller.

The current implementation focuses on the core UAV control path first. Camera, POI, and web UI work remain stretch scope.

## Planned stack

- Python 3.12
- Official `mcp[cli]` SDK / FastMCP
- MAVSDK-Python
- PX4 SITL + Gazebo Harmonic
- Pydantic v2
- pytest + pytest-asyncio

## Repository layout

```text
docs/                  Project documentation intended for review
evaluation/            Benchmark and evaluation scripts
scripts/               Local helper scripts
src/uav_mcp_server/    Application package
tests/                 Unit and integration tests
```

## Implemented core

- shared domain models and environment-backed settings
- navigation helpers for relative movement and geofence math
- telemetry manager with cached snapshot state
- testable drone control layer with a backend protocol and live MAVSDK adapter
- mission planning with bounded waypoint inputs
- safety validation for state, preflight checks, bounds, geofence, and rate limiting
- FastMCP server exposing a safe tool surface and read-only resources
- fast unit and component coverage for the core control path

## Safe MCP tool surface

- `connect`
- `arm`
- `disarm`
- `takeoff`
- `land`
- `hold`
- `rtl`
- `goto_relative`
- `run_mission`
- `get_status`
- `get_telemetry`

## Current status

- Core control, safety, and MCP server layers are implemented.
- Fast local verification is in place with unit and component tests.
- The main remaining blocker for end-to-end validation is live PX4 SITL verification on Ubuntu 24.04 with Python 3.12 and MAVSDK.
- Fast verification in this workspace passed in a local `.venv` with `mcp 1.26.0`, `pydantic 2.12.5`, and `pytest 9.0.2`.

## Quick start

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m uav_mcp_server --transport stdio
```

For HTTP transport:

```bash
python -m uav_mcp_server --transport streamable-http --host 127.0.0.1 --port 8000
```

## Verification

Fast local tests:

```bash
PYTHONPATH=src python -m pytest -q
```

Live SITL verification is documented in [setup.md](docs/setup.md) and [demo.md](docs/demo.md).
