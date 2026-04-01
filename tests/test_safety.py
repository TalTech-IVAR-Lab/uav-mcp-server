from uav_mcp_server.config import Settings
from uav_mcp_server.safety import SafetyValidator
from uav_mcp_server.types import DroneState, ErrorCode, TelemetrySnapshot, WaypointInput


def _ready_snapshot(**overrides: object) -> TelemetrySnapshot:
    values = {
        "state": DroneState.READY,
        "connected": True,
        "battery_percent": 80.0,
        "is_global_position_ok": True,
        "is_home_position_ok": True,
        "latitude_deg": 59.3948,
        "longitude_deg": 24.6614,
        "absolute_altitude_m": 150.0,
        "relative_altitude_m": 10.0,
        "home_absolute_altitude_m": 140.0,
    }
    values.update(overrides)
    return TelemetrySnapshot(**values)


def test_arm_requires_preflight_readiness() -> None:
    validator = SafetyValidator(Settings())

    violation = validator.validate("arm", _ready_snapshot(is_global_position_ok=False))

    assert violation is not None
    assert violation.error_code is ErrorCode.PREFLIGHT_FAILED


def test_arm_rejects_low_battery() -> None:
    validator = SafetyValidator(Settings(min_battery_percent=30))

    violation = validator.validate("arm", _ready_snapshot(battery_percent=20.0))

    assert violation is not None
    assert violation.error_code is ErrorCode.LOW_BATTERY


def test_wrong_state_is_rejected() -> None:
    validator = SafetyValidator(Settings())

    violation = validator.validate("takeoff", _ready_snapshot(state=DroneState.READY), altitude_m=10.0)

    assert violation is not None
    assert violation.error_code is ErrorCode.WRONG_STATE


def test_takeoff_checks_altitude_bounds() -> None:
    validator = SafetyValidator(Settings(min_altitude_m=2.0, max_altitude_m=50.0))

    violation = validator.validate("takeoff", _ready_snapshot(state=DroneState.ARMED), altitude_m=100.0)

    assert violation is not None
    assert violation.error_code is ErrorCode.INVALID_PARAMS


def test_goto_relative_rejects_targets_outside_geofence() -> None:
    validator = SafetyValidator(Settings(geofence_radius_m=30.0))

    violation = validator.validate(
        "goto_relative",
        _ready_snapshot(state=DroneState.AIRBORNE),
        north_m=100.0,
        east_m=0.0,
        altitude_m=20.0,
    )

    assert violation is not None
    assert violation.error_code is ErrorCode.GEOFENCE_VIOLATION


def test_rate_limit_applies_to_action_commands_only() -> None:
    validator = SafetyValidator(Settings(command_rate_limit_per_sec=1))
    snapshot = _ready_snapshot(state=DroneState.ARMED)

    first = validator.validate("takeoff", snapshot, altitude_m=10.0)
    second = validator.validate("takeoff", snapshot, altitude_m=10.0)
    read_only = validator.validate("get_status", snapshot)

    assert first is None
    assert second is not None
    assert second.error_code is ErrorCode.RATE_LIMITED
    assert read_only is None


def test_mission_checks_speed_and_geofence() -> None:
    validator = SafetyValidator(Settings(max_speed_m_s=10.0, geofence_radius_m=500.0))
    snapshot = _ready_snapshot(state=DroneState.AIRBORNE)

    violation = validator.validate(
        "run_mission",
        snapshot,
        waypoints=[
            WaypointInput(latitude_deg=59.3948, longitude_deg=24.6614, altitude_m=20.0, speed_m_s=20.0)
        ],
    )

    assert violation is not None
    assert violation.error_code is ErrorCode.INVALID_PARAMS
