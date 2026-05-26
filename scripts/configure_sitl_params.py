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
# Key insight: top *speed* and *rebound* are independent.
#   Top speed  → MPC_XY_VEL_MAX, MPC_XY_CRUISE (velocity caps)
#   Rebound    → MPC_ACC_HOR_MAX / MPC_JERK_MAX (how aggressively the
#                trajectory ramps the velocity setpoint) plus the
#                position-loop stiffness (MPC_XY_P) and velocity-loop
#                damping (MPC_XY_VEL_D_ACC).
#
# So we keep the velocity caps generous (≈ PX4 default) — the drone can
# still cruise fast — but cap the *rate of change* and damp the inner loop
# so it never overshoots the setpoint it's chasing. End result: same cruise
# speed, smooth ramp in/out, no springback.
#
# Safety-relevant params (battery, geofence, COM_*) are untouched.
#
# AGILE PROFILE (current). The old "rebound" had two real root causes, now
# fixed at the source: (1) the world <magnetic_field> was NED-ordered in an
# ENU slot, so the EKF yaw estimate wobbled; (2) the yaw rate-loop integral
# wound up over long turns and unloaded past the target. With the field
# corrected and MC_YAWRATE_I=0, the airframe no longer needs the glacial
# accel/jerk limits earlier experiments leaned on. So we run a fast, snappy
# envelope and keep only the genuine anti-overshoot knobs (a little velocity-
# loop D, zero yaw integral). Result: quick and agile, still settles clean.
SMOOTH_FLIGHT_PARAMS: dict[str, float] = {
    # ---- Translation top-end (fast cruise) ----
    "MPC_XY_VEL_MAX":    10.0,   # cruise speed cap [m/s]
    "MPC_XY_CRUISE":      9.0,   # auto-mode cruise [m/s]
    "MPC_VEL_MANUAL":    10.0,   # manual position-mode cap [m/s]

    # ---- Ramp limits: snappy accel/jerk for an agile feel. The velocity-loop
    #     D below keeps the ramp-out from springing past the setpoint. ----
    "MPC_ACC_HOR_MAX":    6.0,   # max horizontal accel [m/s²]
    "MPC_ACC_HOR":        5.0,   # nominal horizontal accel [m/s²]
    "MPC_JERK_AUTO":     15.0,   # auto-mode jerk limit [m/s³]
    "MPC_JERK_MAX":      15.0,   # max jerk [m/s³]

    # ---- Vertical envelope (fast climb / descent) ----
    "MPC_Z_VEL_MAX_UP":   6.0,   # climb rate [m/s]
    "MPC_Z_VEL_MAX_DN":   5.0,   # descent rate [m/s]
    "MPC_ACC_UP_MAX":     6.0,   # vertical accel up [m/s²]
    "MPC_ACC_DOWN_MAX":   6.0,   # vertical accel down [m/s²]

    # ---- Position / velocity loop. Back near PX4 default for crisp tracking;
    #     a little extra velocity-loop D is the only retained smoothing. ----
    "MPC_XY_P":           0.95,  # PX4 default position correction
    "MPC_XY_VEL_P_ACC":   1.8,   # PX4 default velocity P
    "MPC_XY_VEL_D_ACC":   0.30,  # mild damping (default 0.2) to settle clean
    "MPC_Z_P":            1.0,   # default altitude position loop
    "MPC_Z_VEL_P_ACC":    4.0,   # default altitude velocity P
    "MPC_Z_VEL_D_ACC":    0.0,   # default

    # ---- Hover hold (PX4 defaults) ----
    "MPC_HOLD_MAX_XY":    0.8,
    "MPC_HOLD_MAX_Z":     0.6,

    # ---- Takeoff / land transitions (a touch snappier) ----
    "MPC_TKO_SPEED":      2.0,   # takeoff climb speed [m/s]
    "MPC_TKO_RAMP_T":     1.5,   # takeoff ramp time [s]
    "MPC_LAND_SPEED":     0.8,   # touchdown speed [m/s]

    # ---- Attitude rate loops (roll/pitch). Agile = PX4-default firmness so
    #     WASD translation snaps to attitude without feeling mushy. ----
    "MC_ROLLRATE_K":      1.0,
    "MC_ROLLRATE_P":      0.15,
    "MC_ROLLRATE_D":      0.003,
    "MC_PITCHRATE_K":     1.0,
    "MC_PITCHRATE_P":     0.15,
    "MC_PITCHRATE_D":     0.003,
    "MC_ROLL_P":          6.5,   # PX4 default - crisp attitude
    "MC_PITCH_P":         6.5,

    # ---- YAW (agile, rebound-free) ----
    # Heading repositions run through GotoControl, whose HeadingSmoothing emits
    # a trapezoidal yaw feed-forward bounded by MPC_YAWRAUTO_MAX (rate) and
    # MPC_YAWRAUTO_ACC (accel/decel) that decelerates the rate to zero AT the
    # target, so the commanded trajectory cannot overshoot. The old rebound was
    # the corrupted mag field (EKF yaw wobble, fixed in the world) plus rate-loop
    # integral windup. We keep MC_YAWRATE_I=0 (the airframe needs no yaw integral
    # — gravity exerts no yaw torque) and otherwise run PX4-default-firm gains
    # for fast, crisp heading control.
    #
    # MPC_YAWRAUTO_MAX also sets the slew rate of the ORBIT yaw setpoint
    # (FlightTaskOrbit), so it must exceed the orbit angular rate ω = v/r or the
    # target drifts off-centre on small radii. At 60 deg/s (=1.05 rad/s) even a
    # 5 m / 3 m·s⁻¹ orbit (ω≈34 deg/s) tracks with margin; orbit speed is also
    # clamped to the yaw capability server-side as a belt-and-suspenders.
    #
    # If any rebound reappears now that agility is the goal, the lever is
    # MC_YAW_P (2.8→2.4), NOT the rate cap — lowering the cap would re-break orbit.
    "MC_YAW_P":           2.8,   # PX4 default — crisp heading, low orbit-framing lag
    "MC_YAWRATE_K":       1.0,
    "MC_YAWRATE_P":       0.25,
    "MC_YAWRATE_I":       0.0,   # zero integral: no wound-up torque to unload → no rebound
    "MC_YAWRATE_D":       0.03,
}
SMOOTH_FLIGHT_PARAMS["MPC_YAWRAUTO_MAX"] = 60.0   # fast yaw + small-orbit framing
SMOOTH_FLIGHT_PARAMS["MPC_YAWRAUTO_ACC"] = 60.0   # PX4 default accel/decel
SMOOTH_FLIGHT_PARAMS["MPC_MAN_Y_MAX"]    = 120.0  # agile manual yaw


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
