# New System Workflow

This document is the canonical install and launch workflow for bringing up the project on a fresh Linux workstation.

## Supported host profiles

Preferred target:
- Ubuntu 24.04
- Python 3.12
- PX4 SITL with Gazebo Harmonic
- launcher selects `gz_x500`

Validated fallback:
- Ubuntu 22.04
- Python 3.12
- PX4 SITL with Gazebo Classic
- launcher selects `gazebo-classic`

The repository is pinned to Python `>=3.12,<3.13`. The fallback path exists because this project was validated on an Ubuntu 22.04 laptop where Gazebo Harmonic packages were not available.

## Expected workspace layout

The launcher assumes the PX4 checkout sits next to this repository:

```text
<workspace>/
  PX4-Autopilot/
  taltech-uav-mcp-server/
```

If you use a different PX4 location, set `PX4_DIR=/absolute/path/to/PX4-Autopilot`.

## 1. Install host prerequisites

Base tools:

```bash
sudo apt update
sudo apt install -y git make cmake pkg-config protobuf-compiler curl
```

Python 3.12:

Preferred on Ubuntu 24.04:

```bash
sudo apt install -y python3.12 python3.12-venv
```

If `python3.12` is not available from the OS, install a rootless copy with `uv`:

```bash
python3 -m pip install --user uv
~/.local/bin/uv python install 3.12
```

Simulator stack:
- Preferred: install the official PX4 and Gazebo Harmonic host dependencies for your Ubuntu release.
- Fallback on Ubuntu 22.04: install Gazebo Classic and its development files.

Gazebo Classic fallback packages:

```bash
sudo apt install -y gazebo libgazebo-dev
```

## 2. Clone the repositories

Clone this repository and PX4 next to each other:

```bash
cd <workspace>
git clone <your-main-repo-url> taltech-uav-mcp-server
git clone --recursive --branch v1.16.0 https://github.com/PX4/PX4-Autopilot.git
```

If you already cloned PX4 without submodules:

```bash
cd <workspace>/PX4-Autopilot
git submodule update --init --recursive
```

## 3. Create the project virtual environment

Using system `python3.12`:

```bash
cd <workspace>/taltech-uav-mcp-server
python3.12 -m venv .venv312
. .venv312/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
```

Using rootless `uv` Python 3.12:

```bash
cd <workspace>/taltech-uav-mcp-server
~/.local/bin/uv venv --seed --python 3.12 .venv312
. .venv312/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
cp .env.example .env
```

The scripts prefer `.venv312` automatically.

## 4. Install PX4 Python-side requirements

PX4 needs its own Python tooling in the same environment used to build and run SITL:

```bash
cd <workspace>/taltech-uav-mcp-server
. .venv312/bin/activate
pip install -r ../PX4-Autopilot/Tools/setup/requirements.txt ninja
```

## 5. Prepare the PX4 checkout

Preferred Gazebo Harmonic path:
- no extra repo-side patching is required
- once the Harmonic development packages are installed, the launcher will prefer `gz_x500`

Gazebo Classic fallback path:
- required on hosts like Ubuntu 22.04 where Gazebo Harmonic is not installed
- apply the local compatibility patch once before building SITL

```bash
cd <workspace>/taltech-uav-mcp-server
scripts/prepare_px4_classic_fallback.sh
```

That helper applies the two local build fixes needed for the Gazebo Classic fallback:
- disable the optional GStreamer plugin in PX4's Gazebo Classic build
- skip the Qt camera plugin unless that optional path is enabled

## 6. Configure the project

Copy the example environment file if you have not already:

```bash
cd <workspace>/taltech-uav-mcp-server
cp .env.example .env
```

Important defaults in `.env`:
- `PX4_CONNECTION_STRING=udpin://0.0.0.0:14540`
- `GEOFENCE_CENTER_LAT` and `GEOFENCE_CENTER_LON`
- `DEFAULT_TAKEOFF_ALTITUDE_M`

The SITL launcher reads `GEOFENCE_CENTER_LAT` and `GEOFENCE_CENTER_LON` from `.env` and uses them as `PX4_HOME_LAT` and `PX4_HOME_LON`. This keeps live `goto_relative` validation aligned with the server's geofence.

## 7. Launch the full live stack

One command:

```bash
cd <workspace>/taltech-uav-mcp-server
scripts/launch_live_stack.sh
```

What it does:
- stops any prior repo-managed live stack
- picks the best supported simulator mode for the host
- starts PX4 SITL headless
- sets `COM_DISARM_PRFLT=60` so manual `arm` then `takeoff` testing does not race PX4's short preflight auto-disarm window
- starts the HTTP MCP server on `127.0.0.1:8000`
- runs an HTTP smoke check before returning

Environment overrides you may use:
- `PX4_DIR=/absolute/path/to/PX4-Autopilot`
- `PX4_MODEL=gz_x500` or `PX4_MODEL=gazebo-classic`
- `HOST=127.0.0.1`
- `PORT=8000`
- `HEADLESS=1`
- `SMOKE_MODE=status|connect|flight`

If `PX4_MODEL` is set explicitly, the launcher does not silently fall back. It fails fast when the requested simulator stack is not installed on the host.

## 8. Validate the running stack

Fast local tests:

```bash
cd <workspace>/taltech-uav-mcp-server
PYTHONPATH=src .venv312/bin/python -m pytest -q
```

Live connect smoke:

```bash
cd <workspace>/taltech-uav-mcp-server
.venv312/bin/python scripts/smoke_http.py --mode connect --url http://127.0.0.1:8000/mcp
```

Full live flight smoke:

```bash
cd <workspace>/taltech-uav-mcp-server
.venv312/bin/python scripts/smoke_http.py --mode flight --url http://127.0.0.1:8000/mcp
```

Opt-in pytest integration smoke:

```bash
cd <workspace>/taltech-uav-mcp-server
RUN_UAV_SITL_TESTS=1 PYTHONPATH=src .venv312/bin/python -m pytest -q tests/test_integration.py
```

## 9. Stop the stack

```bash
cd <workspace>/taltech-uav-mcp-server
scripts/stop_live_stack.sh
```

## 9a. Optional server-only Docker deployment

This path packages only the Python MCP server. PX4 SITL and Gazebo remain on the host.

Build:

```bash
cd <workspace>/taltech-uav-mcp-server
docker build -t uav-mcp-server .
```

Run local backend mode:

```bash
docker run --rm -p 8000:8000 -e BACKEND_MODE=local uav-mcp-server
```

Run live mode on Linux against host PX4:

```bash
cd <workspace>/taltech-uav-mcp-server
BACKEND_MODE=live PX4_CONNECTION_STRING=udpin://0.0.0.0:14540 \
docker compose -f docker-compose.server.yml up --build
```

Notes:
- the compose file uses `network_mode: host`, so this live path is Linux-focused
- the container does not launch PX4 SITL or Gazebo
- keep the host live stack or host PX4 SITL running separately

## 10. Logs and troubleshooting

Repo-managed runtime artifacts:
- `.run/logs/sitl.log`
- `.run/logs/server.log`

Common issues:
- `PX4 directory not found`
  Set `PX4_DIR` or place `PX4-Autopilot` next to this repository.
- `No supported PX4 simulator stack detected`
  Install Gazebo Harmonic for the preferred `gz_x500` path or Gazebo Classic for the fallback path.
- `PX4 model 'gz_x500' requires the Gazebo Harmonic development packages`
  The host has not been provisioned for the preferred simulator yet. Either install the Harmonic dev packages or let the launcher auto-select `gazebo-classic`.
- `goto_relative` rejected by geofence
  Make sure SITL was started through `scripts/launch_live_stack.sh` or `scripts/start_sitl.sh`, not through a raw `make px4_sitl ...` command that bypasses the `.env`-driven home-position alignment.
- live stack starts but MAVSDK cannot connect
  Check that PX4 is listening on UDP `14580` and the server is using `udpin://0.0.0.0:14540`.
- launcher reports a repo-scoped simulator process is still running
  Run `scripts/stop_live_stack.sh --force` once to clear stale simulator leftovers from an earlier failed run, then launch again.

## 11. Recommended operator workflow

Daily use:

```bash
cd <workspace>/taltech-uav-mcp-server
scripts/launch_live_stack.sh
.venv312/bin/python scripts/smoke_http.py --mode connect --url http://127.0.0.1:8000/mcp
```

Before demos or evaluation runs:

```bash
cd <workspace>/taltech-uav-mcp-server
PYTHONPATH=src .venv312/bin/python -m pytest -q
.venv312/bin/python scripts/smoke_http.py --mode flight --url http://127.0.0.1:8000/mcp
```
