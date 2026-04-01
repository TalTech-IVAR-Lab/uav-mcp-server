from uav_mcp_server.config import Settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.telemetry_rate_hz == 5
    assert settings.command_rate_limit_per_sec == 2


def test_settings_accept_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("MAX_SPEED_M_S", "9")
    monkeypatch.setenv("MIN_BATTERY_PERCENT", "35")

    settings = Settings()

    assert settings.max_speed_m_s == 9
    assert settings.min_battery_percent == 35
