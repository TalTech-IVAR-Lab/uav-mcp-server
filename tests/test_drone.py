import asyncio
import sys
from types import SimpleNamespace

import pytest

from tests.fakes import DEFAULT_TEST_LATITUDE_DEG, DEFAULT_TEST_LONGITUDE_DEG, FakeDroneBackend
from uav_mcp_server.config import Settings
from uav_mcp_server.drone import DroneController, MavsdkBackend
from uav_mcp_server.navigation import relative_to_absolute_altitude_m
from uav_mcp_server.telemetry import TelemetryManager
from uav_mcp_server.types import DroneState, ErrorCode, OrbitYawBehavior, WaypointInput


class DelayedArmTelemetryBackend(FakeDroneBackend):
    def __init__(self, arm_delay_s: float = 0.05) -> None:
        super().__init__()
        self._arm_delay_s = arm_delay_s

    async def arm(self) -> None:
        self._raise_if_configured()
        asyncio.create_task(self._publish_armed_after_delay())

    async def _publish_armed_after_delay(self) -> None:
        await asyncio.sleep(self._arm_delay_s)
        await self.publish_armed(True)


class DelayedTakeoffTelemetryBackend(FakeDroneBackend):
    def __init__(self, takeoff_delay_s: float = 0.05) -> None:
        super().__init__()
        self._takeoff_delay_s = takeoff_delay_s

    async def takeoff(self) -> None:
        self._raise_if_configured()
        asyncio.create_task(self._publish_takeoff_after_delay())

    async def _publish_takeoff_after_delay(self) -> None:
        await asyncio.sleep(self._takeoff_delay_s)
        await self.publish_armed(True)
        await self.publish_in_air(True)
        await self.publish_flight_mode("TAKEOFF")


@pytest.mark.asyncio
async def test_controller_connects_and_starts_telemetry() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    result = await controller.connect()

    assert result.success is True
    assert backend.connected_to == Settings().px4_connection_string

    await backend.publish_health()
    await asyncio.sleep(0)
    assert controller.telemetry_manager.get_snapshot().connected is True

    await controller.telemetry_manager.stop()


@pytest.mark.asyncio
async def test_controller_translates_relative_move_to_goto_location() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    await controller.connect()
    await backend.publish_position(absolute_altitude_m=155.0, relative_altitude_m=15.0)
    await backend.publish_home(home_absolute_altitude_m=140.0)
    await backend.publish_attitude(yaw_deg=45.0, pitch_deg=0.0, roll_deg=0.0)
    await asyncio.sleep(0)

    result = await controller.goto_relative(north_m=50.0, east_m=20.0, altitude_m=30.0)

    assert result.success is True
    latitude_deg, longitude_deg, absolute_altitude_m, _ = backend.goto_calls[-1]
    assert latitude_deg != Settings().geofence_center_lat
    assert longitude_deg != Settings().geofence_center_lon
    assert absolute_altitude_m == relative_to_absolute_altitude_m(140.0, 30.0)
    assert backend.goto_calls[-1][3] == 45.0

    await controller.telemetry_manager.stop()


@pytest.mark.asyncio
async def test_controller_dispatches_orbit_to_backend() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    result = await controller.orbit(
        latitude_deg=59.3950,
        longitude_deg=24.6620,
        absolute_altitude_m=152.0,
        radius_m=12.0,
        velocity_m_s=3.0,
        yaw_behavior=OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER,
    )

    assert result.success is True
    assert backend.orbit_calls[-1] == (
        59.3950,
        24.6620,
        152.0,
        12.0,
        3.0,
        OrbitYawBehavior.HOLD_FRONT_TO_CIRCLE_CENTER.value,
    )


@pytest.mark.asyncio
async def test_controller_points_gimbal_at_roi_location() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    await controller.connect()
    await asyncio.sleep(0)

    result = await controller.point_gimbal_at(59.3950, 24.6620, 152.0)

    assert result.success is True
    assert backend.roi_calls[-1] == (59.3950, 24.6620, 152.0)


@pytest.mark.asyncio
async def test_controller_rejects_relative_move_without_position() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    result = await controller.goto_relative(north_m=10.0, east_m=0.0, altitude_m=20.0)

    assert result.success is False
    assert result.error_code is ErrorCode.CONNECTION_LOST


@pytest.mark.asyncio
async def test_controller_runs_mission() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(
        Settings(default_mission_speed_m_s=6.5),
        backend,
        TelemetryManager(),
    )

    result = await controller.run_mission(
        [WaypointInput(latitude_deg=59.4, longitude_deg=24.6, altitude_m=10.0)]
    )

    assert result.success is True
    assert backend.started_missions == 1
    assert len(backend.uploaded_missions[-1]) == 1
    assert backend.uploaded_missions[-1][0].speed_m_s == 6.5


@pytest.mark.asyncio
async def test_controller_guided_takeoff_connects_arms_and_takes_off() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    await backend.publish_position()
    await backend.publish_home()
    await backend.publish_battery()
    await backend.publish_health()
    await backend.publish_armed(False)
    await asyncio.sleep(0)

    result = await controller.guided_takeoff(12.0)

    assert result.success is True
    assert backend.connected_to == Settings().px4_connection_string
    assert backend.takeoff_altitude_m == 12.0

    await controller.telemetry_manager.stop()


@pytest.mark.asyncio
async def test_controller_adjusts_heading_using_current_position() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    await controller.connect()
    await backend.publish_position(absolute_altitude_m=155.0, relative_altitude_m=15.0)
    await backend.publish_home(home_absolute_altitude_m=140.0)
    await backend.publish_attitude(yaw_deg=90.0, pitch_deg=0.0, roll_deg=0.0)
    await backend.publish_battery()
    await backend.publish_health()
    await asyncio.sleep(0)

    result = await controller.yaw_relative(30.0)

    assert result.success is True
    assert backend.goto_calls[-1] == (
        DEFAULT_TEST_LATITUDE_DEG,
        DEFAULT_TEST_LONGITUDE_DEG,
        155.0,
        120.0,
    )

    await controller.telemetry_manager.stop()


@pytest.mark.asyncio
async def test_controller_adjusts_gimbal_pitch_when_supported() -> None:
    backend = FakeDroneBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    await controller.connect()
    await backend.publish_position()
    await backend.publish_home()
    await backend.publish_battery()
    await backend.publish_health()
    await asyncio.sleep(0)

    result = await controller.gimbal_pitch_relative(-10.0)

    assert result.success is True
    assert backend.gimbal_pitch_calls[-1] == -10.0

    await controller.telemetry_manager.stop()


class FakeMavsdkGimbal:
    def __init__(self) -> None:
        self.take_control_calls: list[tuple[int, object]] = []
        self.release_control_calls: list[int] = []
        self.set_angles_calls: list[tuple[int, float, float, float, object, object]] = []
        self.set_roi_calls: list[tuple[int, float, float, float]] = []

    async def take_control(self, gimbal_id: int, control_mode: object) -> None:
        self.take_control_calls.append((gimbal_id, control_mode))
        if gimbal_id == 1:
            raise RuntimeError("device route rejected")

    async def release_control(self, gimbal_id: int) -> None:
        self.release_control_calls.append(gimbal_id)

    async def set_angles(
        self,
        gimbal_id: int,
        roll_deg: float,
        pitch_deg: float,
        yaw_deg: float,
        gimbal_mode: object,
        send_mode: object,
    ) -> None:
        self.set_angles_calls.append(
            (gimbal_id, roll_deg, pitch_deg, yaw_deg, gimbal_mode, send_mode)
        )

    async def set_roi_location(
        self,
        gimbal_id: int,
        latitude_deg: float,
        longitude_deg: float,
        absolute_altitude_m: float,
    ) -> None:
        self.set_roi_calls.append((gimbal_id, latitude_deg, longitude_deg, absolute_altitude_m))

    async def get_attitude(self, gimbal_id: int) -> SimpleNamespace:
        assert gimbal_id == 1
        return SimpleNamespace(euler_angle_forward=SimpleNamespace(pitch_deg=-12.5))


def _install_fake_mavsdk_gimbal(monkeypatch) -> None:
    fake_control_mode = SimpleNamespace(PRIMARY="primary")
    fake_gimbal_mode = SimpleNamespace(YAW_FOLLOW="yaw_follow")
    fake_send_mode = SimpleNamespace(ONCE="once")
    monkeypatch.setitem(
        sys.modules,
        "mavsdk.gimbal",
        SimpleNamespace(
            ControlMode=fake_control_mode,
            GimbalMode=fake_gimbal_mode,
            SendMode=fake_send_mode,
        ),
    )


@pytest.mark.asyncio
async def test_mavsdk_backend_falls_back_to_manager_gimbal_id_for_control(monkeypatch) -> None:
    _install_fake_mavsdk_gimbal(monkeypatch)
    backend = object.__new__(MavsdkBackend)
    fake_gimbal = FakeMavsdkGimbal()
    backend._system = SimpleNamespace(gimbal=fake_gimbal)
    backend._last_known_gimbal_pitch_deg = None
    backend._last_known_gimbal_yaw_deg = 42.0
    backend._first_gimbal_id = lambda: asyncio.sleep(0, result=1)

    await backend.gimbal_pitch_relative(-10.0)

    assert [call[0] for call in fake_gimbal.take_control_calls] == [1, 0]
    assert fake_gimbal.set_angles_calls[0][0] == 0
    assert fake_gimbal.set_angles_calls[0][1] == pytest.approx(0.0)
    assert fake_gimbal.set_angles_calls[0][2] == pytest.approx(-22.5)
    assert fake_gimbal.set_angles_calls[0][3] == pytest.approx(0.0)
    assert backend.current_gimbal_yaw_deg() == pytest.approx(0.0)
    assert fake_gimbal.release_control_calls == [0]


@pytest.mark.asyncio
async def test_mavsdk_backend_uses_manager_gimbal_id_for_roi_commands(monkeypatch) -> None:
    _install_fake_mavsdk_gimbal(monkeypatch)
    backend = object.__new__(MavsdkBackend)
    fake_gimbal = FakeMavsdkGimbal()
    backend._system = SimpleNamespace(gimbal=fake_gimbal)
    backend._last_known_gimbal_pitch_deg = None
    backend._last_known_gimbal_yaw_deg = 0.0
    backend._first_gimbal_id = lambda: asyncio.sleep(0, result=1)

    await backend.set_roi_location(59.3950, 24.6620, 152.0)

    assert [call[0] for call in fake_gimbal.take_control_calls] == [1, 0]
    assert fake_gimbal.set_roi_calls == [(0, 59.3950, 24.6620, 152.0)]
    assert fake_gimbal.release_control_calls == [0]


@pytest.mark.asyncio
async def test_controller_translates_backend_failures() -> None:
    backend = FakeDroneBackend(should_fail=True)
    controller = DroneController(Settings(), backend, TelemetryManager())

    result = await controller.arm()

    assert result.success is False
    assert result.error_code is ErrorCode.BACKEND_ERROR


@pytest.mark.asyncio
async def test_controller_waits_for_armed_telemetry_before_reporting_arm_success() -> None:
    backend = DelayedArmTelemetryBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    await controller.connect()
    await backend.publish_position()
    await backend.publish_home()
    await backend.publish_battery()
    await backend.publish_health()
    await backend.publish_armed(False)
    await asyncio.sleep(0)

    started = asyncio.get_running_loop().time()
    result = await controller.arm()
    elapsed_s = asyncio.get_running_loop().time() - started
    snapshot = controller.telemetry_manager.get_snapshot()

    assert result.success is True
    assert elapsed_s >= 0.04
    assert snapshot.armed is True
    assert snapshot.state is DroneState.ARMED

    await controller.telemetry_manager.stop()


@pytest.mark.asyncio
async def test_controller_waits_for_airborne_telemetry_before_reporting_takeoff_success() -> None:
    backend = DelayedTakeoffTelemetryBackend()
    controller = DroneController(Settings(), backend, TelemetryManager())

    await controller.connect()
    await backend.publish_position()
    await backend.publish_home()
    await backend.publish_battery()
    await backend.publish_health()
    await backend.publish_armed(True)
    await asyncio.sleep(0)

    started = asyncio.get_running_loop().time()
    result = await controller.takeoff(12.0)
    elapsed_s = asyncio.get_running_loop().time() - started
    snapshot = controller.telemetry_manager.get_snapshot()

    assert result.success is True
    assert elapsed_s >= 0.04
    assert backend.takeoff_altitude_m == 12.0
    assert snapshot.in_air is True
    assert snapshot.state is DroneState.AIRBORNE

    await controller.telemetry_manager.stop()


def test_mavsdk_backend_normalizes_battery_percent() -> None:
    backend = object.__new__(MavsdkBackend)

    assert backend._normalize_battery_percent(0.56) == 56.0
    assert backend._normalize_battery_percent(100.0) == 100.0


def test_mavsdk_backend_normalizes_udpin_connection_strings_for_mavsdk() -> None:
    backend = object.__new__(MavsdkBackend)

    assert backend._normalize_connection_string("udpin://0.0.0.0:14540") == "udp://:14540"
    assert backend._normalize_connection_string("udpin://:14541") == "udp://:14541"
