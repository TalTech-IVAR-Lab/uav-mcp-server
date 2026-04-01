"""MCP server entrypoint scaffold."""

from __future__ import annotations

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="UAV MCP server scaffold")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=("stdio", "http"),
        help="Transport mode placeholder for later FastMCP wiring.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    print(
        "UAV MCP server scaffold initialized. "
        f"Selected transport={args.transport}. "
        "Implement FastMCP wiring in src/uav_mcp_server/server.py."
    )

