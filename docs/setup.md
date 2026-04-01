# Setup Notes

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

## Notes

- Docker is acceptable for reproducibility, but native Linux is the preferred development path.
- Camera-dependent work should stay out of the critical path until the core system is stable.
