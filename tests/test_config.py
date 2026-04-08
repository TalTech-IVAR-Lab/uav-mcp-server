from uav_mcp_server.config import Settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.telemetry_rate_hz == 5
    assert settings.command_rate_limit_per_sec == 2
    assert settings.default_takeoff_altitude_m == 10.0
    assert settings.default_mission_speed_m_s == 6.0


def test_settings_accept_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("MAX_SPEED_M_S", "9")
    monkeypatch.setenv("MIN_BATTERY_PERCENT", "35")
    monkeypatch.setenv("MAX_RELATIVE_MOVE_DISTANCE_M", "75")

    settings = Settings()

    assert settings.max_speed_m_s == 9
    assert settings.min_battery_percent == 35
    assert settings.max_relative_move_distance_m == 75
