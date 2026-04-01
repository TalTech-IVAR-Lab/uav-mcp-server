import pytest

from uav_mcp_server.mission import MissionManager
from uav_mcp_server.types import WaypointInput


def test_mission_manager_builds_plan_with_default_speed() -> None:
    manager = MissionManager(default_speed_m_s=12.0)

    plan = manager.build_plan(
        [
            WaypointInput(latitude_deg=59.4, longitude_deg=24.6, altitude_m=20.0),
            WaypointInput(latitude_deg=59.5, longitude_deg=24.7, altitude_m=25.0, speed_m_s=8.0),
        ]
    )

    assert plan[0].speed_m_s == 12.0
    assert plan[0].is_fly_through is True
    assert plan[1].speed_m_s == 8.0
    assert plan[1].is_fly_through is False


def test_mission_manager_rejects_empty_mission() -> None:
    manager = MissionManager(default_speed_m_s=10.0)

    with pytest.raises(ValueError):
        manager.build_plan([])
