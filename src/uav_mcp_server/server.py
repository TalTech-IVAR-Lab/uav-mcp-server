"""FastMCP server wiring for the safe UAV control surface."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Any

from mcp.server.fastmcp import FastMCP

from uav_mcp_server.camera import CameraStreamer
from uav_mcp_server.config import Settings, get_settings
from uav_mcp_server.dashboard import DashboardState, register_dashboard_routes
from uav_mcp_server.drone import DroneController, DroneBackend, MavsdkBackend
from uav_mcp_server.local_backend import LocalSimulationBackend
from uav_mcp_server.navigation import coordinate_offset_m
from uav_mcp_server.projection import CameraParams, DronePose, pixel_to_world
from uav_mcp_server.safety import SafetyValidator
from uav_mcp_server.telemetry import TelemetryManager
from uav_mcp_server.types import (
    CommandResult,
    ErrorCode,
    OrbitYawBehavior,
    TelemetrySnapshot,
    WaypointInput,
)

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
        backend=backend or _build_backend(resolved_settings),
        telemetry_manager=telemetry_manager,
    )
    return ServerServices(
        settings=resolved_settings,
        controller=controller,
        safety=SafetyValidator(resolved_settings),
    )


def _build_backend(settings: Settings) -> DroneBackend:
    if settings.backend_mode == "local":
        return LocalSimulationBackend(
            home_latitude_deg=settings.geofence_center_lat,
            home_longitude_deg=settings.geofence_center_lon,
        )
    return MavsdkBackend()


def create_server(
    services: ServerServices | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> FastMCP:
    resolved_services = services or build_services()
    camera_streamer = CameraStreamer(
        enabled=resolved_services.settings.camera_enabled,
        topic=resolved_services.settings.camera_ros_topic,
        fps=resolved_services.settings.camera_fps,
        helper_python_bin=resolved_services.settings.camera_helper_python_bin,
        ros_setup_script=resolved_services.settings.camera_ros_setup_script,
        helper_gazebo_topic_suffix=resolved_services.settings.camera_gazebo_topic_suffix,
    )
    camera_params = CameraParams(
        width_px=resolved_services.settings.camera_width_px,
        height_px=resolved_services.settings.camera_height_px,
        hfov_rad=resolved_services.settings.camera_hfov_rad,
        focal_length_px=resolved_services.settings.camera_focal_length_px,
        mount_yaw_deg=resolved_services.settings.camera_mount_yaw_deg,
        mount_pitch_deg=resolved_services.settings.camera_mount_pitch_deg,
        mount_roll_deg=resolved_services.settings.camera_mount_roll_deg,
    )
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

    def current_drone_pose() -> DronePose:
        snapshot = current_snapshot()
        if (
            snapshot.latitude_deg is None
            or snapshot.longitude_deg is None
            or snapshot.absolute_altitude_m is None
            or snapshot.relative_altitude_m is None
        ):
            raise RuntimeError("Telemetry pose is incomplete; projection is not available yet.")
        return DronePose(
            lat_deg=snapshot.latitude_deg,
            lon_deg=snapshot.longitude_deg,
            absolute_altitude_m=snapshot.absolute_altitude_m,
            relative_altitude_m=snapshot.relative_altitude_m,
            home_absolute_altitude_m=snapshot.inferred_home_absolute_altitude_m(),
            yaw_deg=snapshot.yaw_deg or 0.0,
            pitch_deg=snapshot.pitch_deg or 0.0,
            roll_deg=snapshot.roll_deg or 0.0,
        )

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
    async def orbit(
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
        radius_m: float,
        velocity_m_s: float = resolved_services.settings.default_mission_speed_m_s,
        yaw_behavior: OrbitYawBehavior = OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER,
    ) -> CommandResult:
        violation = validate(
            "orbit",
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            absolute_altitude_m=absolute_altitude_m,
            radius_m=radius_m,
            velocity_m_s=velocity_m_s,
        )
        if violation is not None:
            return violation
        return await resolved_services.controller.orbit(
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            absolute_altitude_m=absolute_altitude_m,
            radius_m=radius_m,
            velocity_m_s=velocity_m_s,
            yaw_behavior=yaw_behavior,
        )

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
            "min_orbit_radius_m": settings.min_orbit_radius_m,
            "max_orbit_radius_m": settings.max_orbit_radius_m,
            "default_takeoff_altitude_m": settings.default_takeoff_altitude_m,
            "default_mission_speed_m_s": settings.default_mission_speed_m_s,
            "command_rate_limit_per_sec": settings.command_rate_limit_per_sec,
            "min_battery_percent": settings.min_battery_percent,
            "camera_enabled": settings.camera_enabled,
            "camera_ros_topic": settings.camera_ros_topic,
            "camera_fps": settings.camera_fps,
        }

    # --- Dashboard wiring ---
    _tool_dispatch: dict[str, Any] = {
        "connect": connect,
        "arm": arm,
        "disarm": disarm,
        "takeoff": takeoff,
        "land": land,
        "hold": hold,
        "rtl": rtl,
        "goto_relative": goto_relative,
        "orbit": orbit,
        "get_status": get_status,
        "get_telemetry": get_telemetry,
    }

    async def _dashboard_validate_and_run(command_name: str, params: dict[str, Any]) -> CommandResult:
        handler = _tool_dispatch.get(command_name)
        if handler is None:
            return CommandResult.fail(
                f"Unknown command: {command_name}",
                ErrorCode.INVALID_PARAMS,
            )
        try:
            if command_name == "orbit" and isinstance(params.get("yaw_behavior"), str):
                params = {
                    **params,
                    "yaw_behavior": OrbitYawBehavior(params["yaw_behavior"]),
                }
            result = await handler(**params)
        except TypeError as exc:
            return CommandResult.fail(
                f"Invalid parameters for '{command_name}': {exc}",
                ErrorCode.INVALID_PARAMS,
            )
        except ValueError as exc:
            return CommandResult.fail(
                f"Invalid parameters for '{command_name}': {exc}",
                ErrorCode.INVALID_PARAMS,
            )
        if isinstance(result, CommandResult):
            return result
        # get_telemetry returns TelemetrySnapshot
        return CommandResult.ok("Telemetry retrieved.", data=result.model_dump(mode="json"))

    def _dashboard_config() -> dict[str, Any]:
        settings = resolved_services.settings
        return {
            "geofence_center_lat": settings.geofence_center_lat,
            "geofence_center_lon": settings.geofence_center_lon,
            "geofence_radius_m": settings.geofence_radius_m,
            "min_altitude_m": settings.min_altitude_m,
            "max_altitude_m": settings.max_altitude_m,
            "max_speed_m_s": settings.max_speed_m_s,
            "min_orbit_radius_m": settings.min_orbit_radius_m,
            "max_orbit_radius_m": settings.max_orbit_radius_m,
            "default_takeoff_altitude_m": settings.default_takeoff_altitude_m,
            "default_mission_speed_m_s": settings.default_mission_speed_m_s,
            "camera": {
                **camera_streamer.status().to_dict(),
                "params": camera_params.to_dict(),
                "stream_url": "/dashboard/api/camera/stream",
            },
        }

    async def _dashboard_project_pixel(params: dict[str, Any]) -> dict[str, float]:
        try:
            u = float(params["u"])
            v = float(params["v"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Projection requires numeric 'u' and 'v' pixel coordinates.") from exc
        return pixel_to_world(u, v, camera_params, current_drone_pose()).to_dict()

    async def _dashboard_select_and_orbit(params: dict[str, Any]) -> CommandResult:
        try:
            projection = await _dashboard_project_pixel(params)
            snapshot = current_snapshot()
            if snapshot.absolute_altitude_m is None:
                return CommandResult.fail(
                    "Current altitude is unavailable; orbit target altitude cannot be resolved.",
                    ErrorCode.CONNECTION_LOST,
                )
            radius_m = float(params.get("radius_m", 12.0))
            velocity_m_s = float(
                params.get(
                    "velocity_m_s",
                    min(resolved_services.settings.default_mission_speed_m_s, 3.0),
                )
            )
            yaw_behavior = OrbitYawBehavior(
                params.get(
                    "yaw_behavior",
                    OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER.value,
                )
            )
        except ValueError as exc:
            return CommandResult.fail(str(exc), ErrorCode.INVALID_PARAMS)
        except RuntimeError as exc:
            return CommandResult.fail(str(exc), ErrorCode.PREFLIGHT_FAILED)

        result = await _dashboard_validate_and_run(
            "orbit",
            {
                "latitude_deg": projection["latitude_deg"],
                "longitude_deg": projection["longitude_deg"],
                "absolute_altitude_m": float(
                    params.get("absolute_altitude_m", snapshot.absolute_altitude_m)
                ),
                "radius_m": radius_m,
                "velocity_m_s": velocity_m_s,
                "yaw_behavior": yaw_behavior,
            },
        )
        if result.data is None:
            result.data = {}
        result.data["projection"] = projection
        result.data["selection"] = {"u": float(params["u"]), "v": float(params["v"])}
        return result

    async def _dashboard_select_and_approach(params: dict[str, Any]) -> CommandResult:
        try:
            projection = await _dashboard_project_pixel(params)
            snapshot = current_snapshot()
            if snapshot.latitude_deg is None or snapshot.longitude_deg is None:
                return CommandResult.fail(
                    "Current position is unavailable; cannot compute an approach vector.",
                    ErrorCode.CONNECTION_LOST,
                )
            target_altitude_m = float(
                params.get(
                    "altitude_m",
                    snapshot.relative_altitude_m or resolved_services.settings.default_takeoff_altitude_m,
                )
            )
            north_m, east_m = coordinate_offset_m(
                snapshot.latitude_deg,
                snapshot.longitude_deg,
                projection["latitude_deg"],
                projection["longitude_deg"],
            )
        except ValueError as exc:
            return CommandResult.fail(str(exc), ErrorCode.INVALID_PARAMS)
        except RuntimeError as exc:
            return CommandResult.fail(str(exc), ErrorCode.PREFLIGHT_FAILED)

        result = await _dashboard_validate_and_run(
            "goto_relative",
            {
                "north_m": north_m,
                "east_m": east_m,
                "altitude_m": target_altitude_m,
            },
        )
        if result.data is None:
            result.data = {}
        result.data["projection"] = projection
        result.data["selection"] = {"u": float(params["u"]), "v": float(params["v"])}
        return result

    dashboard_state = DashboardState(
        get_snapshot=current_snapshot,
        validate_and_run=_dashboard_validate_and_run,
        get_config=_dashboard_config,
        project_pixel=_dashboard_project_pixel,
        select_and_orbit=_dashboard_select_and_orbit,
        select_and_approach=_dashboard_select_and_approach,
        camera_streamer=camera_streamer,
    )
    register_dashboard_routes(mcp, dashboard_state)

    return mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe UAV MCP server")
    parser.add_argument(
        "--backend",
        default=None,
        choices=("live", "local"),
        help="Backend mode. Use 'local' for API-level testing without PX4 SITL.",
    )
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
    settings = Settings(backend_mode=args.backend) if args.backend is not None else get_settings()
    server = create_server(build_services(settings=settings), host=args.host, port=args.port)
    server.run(transport=transport)
