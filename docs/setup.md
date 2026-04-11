# Setup Notes

The canonical fresh-machine workflow now lives in [new-system-workflow.md](new-system-workflow.md).
Use this file as the short operational summary and keep the detailed installation steps in that document.

## Preferred environment

- Ubuntu 24.04 LTS
- Native PX4 SITL build
- Python 3.12

The repository currently contains a working core implementation, but the target runtime is still Python 3.12 because the project package is pinned to `>=3.12,<3.13` and live MAVSDK validation is expected there.

## Setup steps

1. Install PX4 dependencies with the official Ubuntu setup script.
2. Build and start PX4 SITL with `gz_x500`.
3. Create a Python virtual environment.
4. Install the package in editable mode with development dependencies.
5. Verify MAVSDK can connect to UDP port `14540`.
6. Copy `.env.example` to `.env` if you want to override defaults.
7. Start the MCP server with either stdio or streamable HTTP transport.

If PX4 SITL is not available, use the local backend mode for API-level testing only.

## Common commands

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

Preferred live launch:

```bash
scripts/launch_live_stack.sh
```

This launcher:
- detects whether Gazebo Harmonic support is present and prefers `gz_x500` when it is
- falls back to `gazebo-classic` on hosts like Ubuntu 22.04 that only have Gazebo Classic installed
- accepts only `PX4_MODEL=gz_x500` or `PX4_MODEL=gazebo-classic` as explicit overrides and fails fast if the requested host stack is missing
- aligns PX4 home latitude and longitude with the configured geofence
- starts the HTTP MCP server and runs an HTTP smoke check

For a brand-new workstation:
- follow [new-system-workflow.md](new-system-workflow.md) from top to bottom
- use `scripts/prepare_px4_classic_fallback.sh` only on the Gazebo Classic fallback path
- use `scripts/stop_live_stack.sh` to shut down the repo-managed live stack cleanly

For local API testing without PX4 or MAVSDK:

```bash
PYTHONPATH=src python3 -m uav_mcp_server --transport streamable-http --backend local --host 127.0.0.1 --port 8000
```

## Server-only Docker

The Docker path packages only the Python MCP server. PX4 SITL and Gazebo remain on the host.

Build the image:

```bash
docker build -t uav-mcp-server .
```

Run local backend mode:

```bash
docker run --rm -p 8000:8000 -e BACKEND_MODE=local uav-mcp-server
```

Run live mode on Linux with host networking:

```bash
BACKEND_MODE=live PX4_CONNECTION_STRING=udpin://0.0.0.0:14540 \
docker compose -f docker-compose.server.yml up --build
```

## Notes

- Docker is acceptable for reproducibility, but native Linux is the preferred development path.
- Camera-dependent work should stay out of the critical path until the core system is stable.
- `--backend local` is only for API-level and UI/client testing. It does not replace live SITL validation.
- Fast local verification can run against the fake backend, but PX4 SITL validation still needs to happen on the target Python 3.12 environment before evaluation work starts.
