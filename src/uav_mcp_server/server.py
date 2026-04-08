"""FastMCP server wiring for the safe UAV control surface."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from uav_mcp_server.config import Settings, get_settings
from uav_mcp_server.drone import DroneController, DroneBackend, MavsdkBackend
from uav_mcp_server.safety import SafetyValidator
from uav_mcp_server.telemetry import TelemetryManager
from uav_mcp_server.types import CommandResult, TelemetrySnapshot, WaypointInput

SERVER_INSTRUCTIONS = (
    "Safe UAV control server for PX4 SITL. Tools expose bounded, high-level actions "
    "only and all actuation paths pass through safety validation before control."
)


@dataclass(slots=True)
class ServerServices:
    settings: Settings
    controller: DroneController
    safety: SafetyValidator


def build_services(
    *,
    settings: Settings | None = None,
    backend: DroneBackend | None = None,
) -> ServerServices:
    resolved_settings = settings or get_settings()
    telemetry_manager = TelemetryManager()
    controller = DroneController(
        settings=resolved_settings,
        backend=backend or MavsdkBackend(),
        telemetry_manager=telemetry_manager,
    )
    return ServerServices(
        settings=resolved_settings,
        controller=controller,
        safety=SafetyValidator(resolved_settings),
    )


def create_server(
    services: ServerServices | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    resolved_services = services or build_services()
    mcp = FastMCP(
        name="UAV Control Server",
        instructions=SERVER_INSTRUCTIONS,
        json_response=True,
        stateless_http=True,
        log_level=resolved_services.settings.log_level.upper(),
        host=host,
        port=port,
    )

    def current_snapshot() -> TelemetrySnapshot:
        return resolved_services.controller.telemetry_manager.get_snapshot()

    def validate(command_name: str, **kwargs: Any) -> CommandResult | None:
        return resolved_services.safety.validate(command_name, current_snapshot(), **kwargs)

    @mcp.tool()
    async def connect(connection_string: str | None = None) -> CommandResult:
        violation = validate("connect")
        if violation is not None:
            return violation
        return await resolved_services.controller.connect(connection_string)

    @mcp.tool()
    async def arm() -> CommandResult:
        violation = validate("arm")
        if violation is not None:
            return violation
        return await resolved_services.controller.arm()

    @mcp.tool()
    async def disarm() -> CommandResult:
        violation = validate("disarm")
        if violation is not None:
            return violation
        return await resolved_services.controller.disarm()

    @mcp.tool()
    async def takeoff(
        altitude_m: float = resolved_services.settings.default_takeoff_altitude_m,
    ) -> CommandResult:
        violation = validate("takeoff", altitude_m=altitude_m)
        if violation is not None:
            return violation
        return await resolved_services.controller.takeoff(altitude_m)

    @mcp.tool()
    async def land() -> CommandResult:
        violation = validate("land")
        if violation is not None:
            return violation
        return await resolved_services.controller.land()

    @mcp.tool()
    async def hold() -> CommandResult:
        violation = validate("hold")
        if violation is not None:
            return violation
        return await resolved_services.controller.hold()

    @mcp.tool()
    async def rtl() -> CommandResult:
        violation = validate("rtl")
        if violation is not None:
            return violation
        return await resolved_services.controller.rtl()

    @mcp.tool()
    async def goto_relative(
        north_m: float,
        east_m: float,
        altitude_m: float,
    ) -> CommandResult:
        violation = validate(
            "goto_relative",
            north_m=north_m,
            east_m=east_m,
            altitude_m=altitude_m,
        )
        if violation is not None:
            return violation
        return await resolved_services.controller.goto_relative(north_m, east_m, altitude_m)

    @mcp.tool()
    async def run_mission(waypoints: list[WaypointInput]) -> CommandResult:
        violation = validate("run_mission", waypoints=waypoints)
        if violation is not None:
            return violation
        return await resolved_services.controller.run_mission(waypoints)

    @mcp.tool()
    async def get_status() -> CommandResult:
        violation = validate("get_status")
        if violation is not None:
            return violation
        return await resolved_services.controller.get_status()

    @mcp.tool()
    async def get_telemetry() -> TelemetrySnapshot:
        violation = validate("get_telemetry")
        if violation is not None:
            return current_snapshot()
        return await resolved_services.controller.get_telemetry()

    @mcp.resource("uav://status/state")
    def status_state() -> str:
        return current_snapshot().state.value

    @mcp.resource("uav://telemetry/snapshot")
    def telemetry_snapshot() -> TelemetrySnapshot:
        return current_snapshot()

    @mcp.resource("uav://config/safety")
    def safety_config() -> dict[str, object]:
        settings = resolved_services.settings
        return {
            "geofence_center_lat": settings.geofence_center_lat,
            "geofence_center_lon": settings.geofence_center_lon,
            "geofence_radius_m": settings.geofence_radius_m,
            "min_altitude_m": settings.min_altitude_m,
            "max_altitude_m": settings.max_altitude_m,
            "max_speed_m_s": settings.max_speed_m_s,
            "max_relative_move_distance_m": settings.max_relative_move_distance_m,
            "default_takeoff_altitude_m": settings.default_takeoff_altitude_m,
            "default_mission_speed_m_s": settings.default_mission_speed_m_s,
            "command_rate_limit_per_sec": settings.command_rate_limit_per_sec,
            "min_battery_percent": settings.min_battery_percent,
        }

    return mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe UAV MCP server")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=("stdio", "streamable-http", "http"),
        help="Transport mode for the FastMCP server.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host.")
    parser.add_argument("--port", default=8000, type=int, help="HTTP bind port.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    transport = "streamable-http" if args.transport == "http" else args.transport
    server = create_server(host=args.host, port=args.port)
    server.run(transport=transport)
