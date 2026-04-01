from uav_mcp_server.config import Settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.telemetry_rate_hz == 5
    assert settings.command_rate_limit_per_sec == 2

