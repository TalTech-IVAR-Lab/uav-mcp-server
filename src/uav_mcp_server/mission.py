"""Mission planning and execution helpers."""

from __future__ import annotations

from typing import Protocol

from uav_mcp_server.types import CommandResult, MissionWaypoint, WaypointInput


class MissionBackend(Protocol):
    async def upload_mission(self, waypoints: list[MissionWaypoint]) -> None: ...

    async def start_mission(self) -> None: ...


class MissionManager:
    """Converts validated waypoint inputs into executable mission plans."""

    def __init__(self, default_speed_m_s: float) -> None:
        self._default_speed_m_s = default_speed_m_s

    def build_plan(self, waypoints: list[WaypointInput]) -> list[MissionWaypoint]:
        if not waypoints:
            raise ValueError("At least one waypoint is required to build a mission.")

        return [
            MissionWaypoint(
                latitude_deg=waypoint.latitude_deg,
                longitude_deg=waypoint.longitude_deg,
                relative_altitude_m=waypoint.altitude_m,
                speed_m_s=waypoint.speed_m_s or self._default_speed_m_s,
                is_fly_through=index < len(waypoints) - 1,
            )
            for index, waypoint in enumerate(waypoints)
        ]

    async def run(
        self,
        backend: MissionBackend,
        waypoints: list[WaypointInput],
    ) -> CommandResult:
        mission_plan = self.build_plan(waypoints)
        await backend.upload_mission(mission_plan)
        await backend.start_mission()
        return CommandResult.ok(
            "Mission uploaded and started.",
            data={"waypoint_count": len(mission_plan)},
        )
