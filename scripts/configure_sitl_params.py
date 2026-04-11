#!/usr/bin/env python3
"""Apply PX4 SITL parameter overrides that make manual testing reliable."""

from __future__ import annotations

import argparse
from contextlib import suppress

import anyio
from mavsdk import System


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure PX4 SITL parameters.")
    parser.add_argument("--system-address", default="udpin://0.0.0.0:14540")
    parser.add_argument("--preflight-auto-disarm-s", default=60.0, type=float)
    parser.add_argument("--timeout-s", default=30.0, type=float)
    return parser


async def run(args: argparse.Namespace) -> None:
    drone = System()
    connected = False
    with anyio.move_on_after(args.timeout_s) as scope:
        await drone.connect(system_address=args.system_address)
        async for state in drone.core.connection_state():
            if state.is_connected:
                connected = True
                break

    if scope.cancelled_caught or not connected:
        raise TimeoutError(
            f"Timed out after {args.timeout_s:.1f}s waiting for MAVSDK on {args.system_address}."
        )

    current_value = await drone.param.get_param_float("COM_DISARM_PRFLT")
    if current_value != args.preflight_auto_disarm_s:
        await drone.param.set_param_float("COM_DISARM_PRFLT", args.preflight_auto_disarm_s)

    updated_value = await drone.param.get_param_float("COM_DISARM_PRFLT")
    print(f"COM_DISARM_PRFLT={updated_value}", flush=True)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    with suppress(KeyboardInterrupt):
        anyio.run(run, args)


if __name__ == "__main__":
    main()
