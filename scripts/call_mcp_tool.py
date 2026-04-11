#!/usr/bin/env python3
"""Call one MCP tool over the streamable HTTP endpoint."""

from __future__ import annotations

import argparse
import json

import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Call an MCP tool over HTTP.")
    parser.add_argument("tool", nargs="?", help="Tool name to call.")
    parser.add_argument(
        "arguments",
        nargs="?",
        default="{}",
        help='JSON object with tool arguments, for example: \'{"altitude_m": 3.0}\'',
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000/mcp", help="MCP HTTP endpoint.")
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="List the server tools instead of calling one.",
    )
    return parser


async def run(args: argparse.Namespace) -> None:
    async with streamable_http_client(args.url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            if args.list_tools:
                result = await session.list_tools()
                print(json.dumps([tool.name for tool in result.tools], indent=2))
                return

            if not args.tool:
                raise SystemExit("tool is required unless --list-tools is used")

            try:
                arguments = json.loads(args.arguments)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"invalid JSON arguments: {exc}") from exc

            if not isinstance(arguments, dict):
                raise SystemExit("arguments must decode to a JSON object")

            result = await session.call_tool(args.tool, arguments)
            payload = {
                "is_error": result.isError,
                "structured": result.structuredContent,
                "content": [item.model_dump(mode="json") for item in result.content],
            }
            print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    anyio.run(run, args)


if __name__ == "__main__":
    main()
