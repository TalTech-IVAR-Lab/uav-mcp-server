# UAV MCP Server

This repository contains a simulation-first UAV control stack for a thesis project. It connects an AI client or operator dashboard to a PX4-based vehicle through a safety-gated Model Context Protocol (MCP) server.

The project is designed for two workflows:

- live PX4 SITL with Gazebo for realistic flight testing
- local backend mode for API, UI, and assistant-flow testing without PX4

## Feature Overview

- Safe MCP tool surface for connect, launch, movement, orbit, mission, hold, RTL, and telemetry queries
- Safety layer for state gating, preflight checks, geofence enforcement, altitude and speed limits, and rate limiting
- Operator dashboard with telemetry, event stream, live map, target management, manual controls, and camera targeting
- Read-only observability dashboard for thesis latency, reliability, safety, and runtime evidence
- Visual target workflows for approach and orbit around a selected map or camera target
- Gimbal pitch control with forward-facing alignment and ROI-based target tracking during orbit workflows
- AI copilot chat for planning and executing dashboard commands, with queued execution when multiple requests are sent
- Local backend for fast testing without MAVSDK or PX4 SITL
- Evaluation and benchmark scripts for latency, reliability, and safety runs

## Repository Layout

```text
docs/                  Architecture, setup, demo, and evaluation notes
evaluation/            Benchmark clients and result processing
scripts/               Launch, smoke-test, and helper scripts
sim/                   Gazebo Classic worlds and models
src/uav_mcp_server/    Application package
tests/                 Unit and component tests
tools/                 Native helpers such as the Gazebo camera bridge
```

## Supported Host Profiles

Preferred target:

- Ubuntu 24.04
- Python 3.12
- PX4 SITL with Gazebo Harmonic

Validated fallback:

- Ubuntu 22.04
- Python 3.12
- PX4 SITL with Gazebo Classic

The package is pinned to Python `>=3.12,<3.13`.

## Step-By-Step Setup On A New Machine

### 1. Install base host packages

```bash
sudo apt update
sudo apt install -y git make cmake pkg-config protobuf-compiler curl
```

Install Python 3.12:

```bash
sudo apt install -y python3.12 python3.12-venv
```

If your distro does not ship `python3.12`, install a user-local copy with `uv`:

```bash
python3 -m pip install --user uv
~/.local/bin/uv python install 3.12
```

For Gazebo Classic fallback hosts:

```bash
sudo apt install -y gazebo libgazebo-dev
```

### 2. Clone PX4 and this repository side by side

The launch scripts assume this layout:

```text
<workspace>/
  PX4-Autopilot/
  taltech-uav-mcp-server/
```

Clone both repositories:

```bash
cd <workspace>
git clone <your-repo-url> taltech-uav-mcp-server
git clone --recursive --branch v1.16.0 https://github.com/PX4/PX4-Autopilot.git
```

If PX4 is already cloned without submodules:

```bash
cd <workspace>/PX4-Autopilot
git submodule update --init --recursive
```

### 3. Create the Python environment

Using system Python:

```bash
cd <workspace>/taltech-uav-mcp-server
python3.12 -m venv .venv312
. .venv312/bin/activate
pip install --upgrade pip
```

Using `uv` Python:

```bash
cd <workspace>/taltech-uav-mcp-server
~/.local/bin/uv venv --seed --python 3.12 .venv312
. .venv312/bin/activate
pip install --upgrade pip
```

### 4. Install project dependencies

```bash
cd <workspace>/taltech-uav-mcp-server
. .venv312/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Optional camera extras:

```bash
pip install -e ".[camera]"
```

### 5. Install PX4 Python-side build requirements

```bash
cd <workspace>/taltech-uav-mcp-server
. .venv312/bin/activate
pip install -r ../PX4-Autopilot/Tools/setup/requirements.txt ninja
```

### 6. Configure the project

Copy the example environment file if you have not already:

```bash
cd <workspace>/taltech-uav-mcp-server
cp .env.example .env
```

Review the important values in `.env`:

- `PX4_CONNECTION_STRING`
- `GEOFENCE_CENTER_LAT`
- `GEOFENCE_CENTER_LON`
- `DEFAULT_TAKEOFF_ALTITUDE_M`
- `CAMERA_ENABLED`
- `GEMINI_API_KEY` if you want live AI planning instead of fallback parsing

If PX4 is not next to this repository, set:

```bash
export PX4_DIR=/absolute/path/to/PX4-Autopilot
```

### 7. Prepare the PX4 checkout when using Gazebo Classic fallback

Only needed on fallback hosts such as Ubuntu 22.04:

```bash
cd <workspace>/taltech-uav-mcp-server
scripts/prepare_px4_classic_fallback.sh
```

### 8. Launch the full live stack

Preferred launcher:

```bash
cd <workspace>/taltech-uav-mcp-server
scripts/launch_live_stack.sh
```

What this does:

- stops any existing repo-managed stack
- selects the best supported simulator mode for the host
- starts PX4 SITL headless
- starts the HTTP MCP server on `127.0.0.1:8000`
- runs a smoke check before returning

Optional overrides:

```bash
export PX4_MODEL=gz_x500
export HOST=127.0.0.1
export PORT=8000
export HEADLESS=1
```

For the TalTech campus world:

```bash
cd <workspace>/taltech-uav-mcp-server
scripts/launch_taltech_live_stack.sh
```

### 9. Open the server and dashboard

After launch:

- MCP HTTP endpoint: `http://127.0.0.1:8000/mcp`
- Operator dashboard: `http://127.0.0.1:8000/dashboard/`
- Observability dashboard: `http://127.0.0.1:8000/dashboard/observability/`

### 10. Verify the installation

Run the fast local test suite:

```bash
cd <workspace>/taltech-uav-mcp-server
PYTHONPATH=src .venv312/bin/python -m pytest -q
```

Run the HTTP smoke test:

```bash
cd <workspace>/taltech-uav-mcp-server
.venv312/bin/python scripts/smoke_http.py --mode connect --url http://127.0.0.1:8000/mcp
```

Run the full flight smoke test:

```bash
cd <workspace>/taltech-uav-mcp-server
.venv312/bin/python scripts/smoke_http.py --mode flight --url http://127.0.0.1:8000/mcp
```

### 11. Stop the stack

```bash
cd <workspace>/taltech-uav-mcp-server
scripts/stop_live_stack.sh
```

## Local Backend Mode

For UI and API testing without PX4 or MAVSDK:

```bash
cd <workspace>/taltech-uav-mcp-server
PYTHONPATH=src python3 -m uav_mcp_server --transport streamable-http --backend local --host 127.0.0.1 --port 8000
```

This mode is useful for:

- dashboard development
- assistant planning and execution flow testing
- API-level smoke tests

It is not a replacement for live SITL validation.

## Server-Only Docker Path

This image packages the Python MCP server only. PX4 SITL and Gazebo still run on the host.

Build:

```bash
docker build -t uav-mcp-server .
```

Run in local backend mode:

```bash
docker run --rm -p 8000:8000 -e BACKEND_MODE=local uav-mcp-server
```

Run in live mode against host PX4:

```bash
BACKEND_MODE=live PX4_CONNECTION_STRING=udpin://0.0.0.0:14540 \
docker compose -f docker-compose.server.yml up --build
```

## Additional Docs

- Fresh-machine workflow: [docs/new-system-workflow.md](docs/new-system-workflow.md)
- Setup summary: [docs/setup.md](docs/setup.md)
- Architecture: [docs/architecture.md](docs/architecture.md)
- Demo notes: [docs/demo.md](docs/demo.md)
- Evaluation notes: [docs/evaluation.md](docs/evaluation.md)
