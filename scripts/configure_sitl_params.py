#!/usr/bin/env python3
"""Apply PX4 SITL parameter overrides that make manual testing reliable."""

from __future__ import annotations

import argparse
from contextlib import suppress
from time import monotonic
from typing import Any
from urllib.parse import urlparse

import anyio


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure PX4 SITL parameters.")
    parser.add_argument("--system-address", default="udpin://0.0.0.0:14540")
    parser.add_argument("--preflight-auto-disarm-s", default=60.0, type=float)
    parser.add_argument("--timeout-s", default=30.0, type=float)
    return parser


def normalize_system_address(system_address: str) -> str:
    parsed = urlparse(system_address)
    if parsed.scheme != "udpin":
        return system_address

    host = parsed.hostname or ""
    port = parsed.port or 14540
    if host in {"", "0.0.0.0"}:
        return f"udp://:{port}"
    return f"udp://{host}:{port}"


def create_system() -> Any:
    from mavsdk import System

    return System()


def stop_mavsdk_server(drone: Any | None) -> None:
    if drone is None:
        return

    stop_server = getattr(drone, "_stop_mavsdk_server", None)
    if callable(stop_server):
        stop_server()


async def wait_for_connection(drone: Any, timeout_s: float) -> bool:
    connected = False
    with anyio.move_on_after(timeout_s) as scope:
        async for state in drone.core.connection_state():
            if state.is_connected:
                connected = True
                break

    return connected and not scope.cancelled_caught


async def connect_system(
    system_address: str,
    timeout_s: float,
    *,
    attempt_timeout_s: float = 10.0,
    retry_interval_s: float = 1.0,
    system_factory: Any = create_system,
) -> Any:
    normalized_address = normalize_system_address(system_address)
    deadline = monotonic() + timeout_s
    last_exc: Exception | None = None

    while True:
        remaining_s = deadline - monotonic()
        if remaining_s <= 0:
            break

        drone = system_factory()
        try:
            await drone.connect(system_address=normalized_address)
            if await wait_for_connection(drone, min(attempt_timeout_s, remaining_s)):
                return drone
        except Exception as exc:
            last_exc = exc

        stop_mavsdk_server(drone)
        await anyio.sleep(min(retry_interval_s, max(0.0, deadline - monotonic())))

    detail = f" Last error: {last_exc}" if last_exc is not None else ""
    raise TimeoutError(
        f"Timed out after {timeout_s:.1f}s waiting for MAVSDK on {normalized_address}.{detail}"
    )


async def _set_float_if_needed(drone: Any, name: str, value: float) -> float:
    """Apply a PX4 float param only when the runtime value differs.

    Returns the post-write value (or current value if unchanged).
    """
    current = await drone.param.get_param_float(name)
    if abs(current - value) > 1e-6:
        await drone.param.set_param_float(name, value)
        return await drone.param.get_param_float(name)
    return current


# Smoothing overrides for SITL: PX4's default x500 MPC is tuned aggressive for
# real-vehicle response. In SITL on the TalTech world the snappy accel/jerk
# limits show as overshoot-then-correct after every manual move ("rebound").
#
# This preset trades top-end agility for "no rebound" handling:
#   - Accel/jerk caps roughly halved → the trajectory generator never feeds
#     the velocity loop a step it can't follow, so the drone settles into the
#     setpoint instead of overshooting it.
#   - Position loop softened (MPC_XY_P) and velocity loop damped
#     (MPC_XY_VEL_D_ACC) so the inner controller doesn't spring back when the
#     trajectory ends.
#   - Takeoff / land speeds reduced and ramp lengthened so transitions in/out
#     of hover are visually smooth.
#   - Yaw rate cap lowered for the same reason on rotation.
# Safety-relevant params (battery, geofence, COM_*) are untouched.
SMOOTH_FLIGHT_PARAMS: dict[str, float] = {
    # ---- Translation envelope (kept slow + smooth) ----
    "MPC_XY_VEL_MAX":     2.0,   # cruise speed cap [m/s]
    "MPC_XY_CRUISE":      1.5,   # auto-mode cruise [m/s]
    "MPC_VEL_MANUAL":     2.0,   # manual position-mode cap [m/s]
    "MPC_ACC_HOR_MAX":    1.0,   # max horizontal accel [m/s²]
    "MPC_ACC_HOR":        0.8,   # nominal horizontal accel [m/s²]
    "MPC_JERK_AUTO":      2.5,   # auto-mode jerk limit [m/s³]
    "MPC_JERK_MAX":       2.5,   # max jerk [m/s³]

    # ---- Vertical envelope ----
    "MPC_Z_VEL_MAX_UP":   1.5,   # climb rate [m/s]
    "MPC_Z_VEL_MAX_DN":   1.0,   # descent rate [m/s]
    "MPC_ACC_UP_MAX":     1.5,   # vertical accel up [m/s²]
    "MPC_ACC_DOWN_MAX":   1.5,   # vertical accel down [m/s²]

    # ---- Yaw ----
    "MPC_YAWRAUTO_MAX":  20.0,   # auto yaw rate [deg/s]
    "MPC_MAN_Y_MAX":     45.0,   # manual yaw rate [deg/s]

    # ---- Position / velocity loop damping (the actual rebound fix) ----
    "MPC_XY_P":           0.85,  # softer position correction (default 0.95)
    "MPC_XY_VEL_P_ACC":   1.6,   # slightly lower velocity P (default 1.8)
    "MPC_XY_VEL_D_ACC":   0.30,  # +damping in velocity loop (default 0.2)

    # ---- Smooth takeoff / land transitions ----
    "MPC_TKO_SPEED":      1.0,   # takeoff climb speed [m/s]
    "MPC_TKO_RAMP_T":     3.0,   # takeoff ramp time [s]
    "MPC_LAND_SPEED":     0.5,   # touchdown speed [m/s]
}


async def run(args: argparse.Namespace) -> None:
    drone = await connect_system(args.system_address, args.timeout_s)
    try:
        com_disarm = await _set_float_if_needed(
            drone, "COM_DISARM_PRFLT", args.preflight_auto_disarm_s
        )
        print(f"COM_DISARM_PRFLT={com_disarm}", flush=True)

        for name, value in SMOOTH_FLIGHT_PARAMS.items():
            try:
                final = await _set_float_if_needed(drone, name, value)
                print(f"{name}={final}", flush=True)
            except Exception as exc:
                # Param missing on this firmware build → skip without failing
                # the whole launcher. Logged so it's traceable on regression.
                print(f"{name}: skipped ({exc})", flush=True)
    finally:
        stop_mavsdk_server(drone)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    with suppress(KeyboardInterrupt):
        anyio.run(run, args)


if __name__ == "__main__":
    main()
