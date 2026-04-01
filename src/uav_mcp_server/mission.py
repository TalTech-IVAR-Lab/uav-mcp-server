"""Mission planning and execution helpers."""

from __future__ import annotations

from uav_mcp_server.types import CommandResult, WaypointInput


class MissionManager:
    """Converts validated waypoint inputs into executable mission plans."""

    async def run(self, waypoints: list[WaypointInput]) -> CommandResult:
        return CommandResult(
            success=False,
            message="Mission execution is not implemented in the initial scaffold.",
            data={"waypoint_count": len(waypoints)},
        )

