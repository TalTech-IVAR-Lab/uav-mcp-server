# UAV MCP Server

This repository contains a simulation-first UAV control middleware for a thesis project built around the Model Context Protocol (MCP). The target system connects an AI agent to a PX4-based UAV running in Software-In-The-Loop (SITL), with a safety layer between the MCP tool surface and the flight controller.

The current implementation covers the core UAV control path and includes a thin operator dashboard for real-time telemetry and manual command execution. Camera, POI, and voice control remain stretch scope.

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
- A local `--backend local` mode is available for API-level testing without PX4 SITL or MAVSDK.
- Live SITL is validated on this workspace through the repo-managed launch path.
- The preferred deployment target remains Ubuntu 24.04 with Gazebo Harmonic, while Ubuntu 22.04 is currently supported through a Gazebo Classic fallback.

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

For the best live launch path on a workstation with PX4 already checked out next to this repo:

```bash
scripts/launch_live_stack.sh
```

The launcher starts PX4 SITL headless, picks `gz_x500` when Gazebo Harmonic is available, falls back to `gazebo-classic` otherwise, aligns the SITL home position with the configured geofence, starts the HTTP MCP server, and runs a smoke check before returning.

The supported explicit `PX4_MODEL` values for the launcher are `gz_x500` and `gazebo-classic`. If you request a model that is not supported on the current host, the launcher fails fast instead of silently falling back.

For full install and launch instructions on a fresh workstation, see [new-system-workflow.md](docs/new-system-workflow.md).

For local API testing without PX4 SITL:

```bash
PYTHONPATH=src python3 -m uav_mcp_server --transport streamable-http --backend local --host 127.0.0.1 --port 8000
```

## Server-only Docker

The repository now includes a server-only container path. It packages the Python MCP server, not PX4 or Gazebo.

Local backend mode:

```bash
docker build -t uav-mcp-server .
docker run --rm -p 8000:8000 -e BACKEND_MODE=local uav-mcp-server
```

Live mode against host PX4 on Linux:

```bash
docker compose -f docker-compose.server.yml up --build
```

For live mode, keep PX4 SITL on the host and set `BACKEND_MODE=live` plus `PX4_CONNECTION_STRING=udpin://0.0.0.0:14540`.

## Operator Dashboard

When the server runs in HTTP mode, a thin operator dashboard is available at `/dashboard/`. It provides:

- Real-time telemetry via Server-Sent Events (SSE)
- Manual command execution through the same safety layer as MCP tools
- Event log with command results and safety rejections

The dashboard loads as a single HTML page with no external build system or CDN dependencies. QGroundControl can stay connected while the dashboard is in use.

## Verification

Fast local tests:

```bash
PYTHONPATH=src python -m pytest -q
```

Live SITL verification is documented in [setup.md](docs/setup.md) and [demo.md](docs/demo.md).
