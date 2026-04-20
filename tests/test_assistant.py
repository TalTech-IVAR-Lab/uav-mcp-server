from __future__ import annotations

import pytest

from uav_mcp_server.assistant import (
    AssistantGroundingContext,
    AssistantTarget,
    AssistantToolCall,
    DashboardAssistant,
    _extract_json_payload,
)
from uav_mcp_server.config import Settings
from uav_mcp_server.types import DroneState, TelemetrySnapshot


def _snapshot() -> TelemetrySnapshot:
    return TelemetrySnapshot(
        state=DroneState.AIRBORNE,
        connected=True,
        armed=True,
        in_air=True,
        latitude_deg=46.2331,
        longitude_deg=6.0556,
        absolute_altitude_m=150.0,
        relative_altitude_m=10.0,
        home_absolute_altitude_m=140.0,
        yaw_deg=90.0,
        battery_percent=85.0,
        is_global_position_ok=True,
        is_home_position_ok=True,
        is_gyrometer_calibration_ok=True,
        is_accelerometer_calibration_ok=True,
    )


def test_extract_json_payload_accepts_fenced_json() -> None:
    payload = _extract_json_payload(
        """```json
{"assistant_text":"ok","calls":[]}
```"""
    )

    assert payload["assistant_text"] == "ok"
    assert payload["calls"] == []


def _grounding() -> AssistantGroundingContext:
    return AssistantGroundingContext(
        source="test",
        command_manifest=[
            {
                "name": "guided_takeoff",
                "label": "Guided Takeoff",
                "hint": "Launch safely.",
                "params": ["altitude_m"],
                "required_params": ["altitude_m"],
            }
        ],
        server_instructions="safe server",
        workflow_guide="Prefer guided takeoff.",
        operator_prompt="Translate requests into safe calls.",
        safety_config={"min_altitude_m": 2.0, "max_altitude_m": 120.0},
    )


@pytest.mark.asyncio
async def test_dashboard_assistant_prefers_gemini_when_available(monkeypatch) -> None:
    assistant = DashboardAssistant(Settings(_env_file=None, gemini_api_key="test-key"))

    def fake_plan_with_gemini(*args, **kwargs):
        return type(
            "GeminiResult",
            (),
            {
                "assistant_text": "Use guided takeoff.",
                "calls": [
                    AssistantToolCall(
                        name="guided_takeoff",
                        arguments={"altitude_m": 10.0},
                        summary="Guided takeoff to 10 meters.",
                    )
                ],
            },
        )()

    monkeypatch.setattr(assistant, "_plan_with_gemini", fake_plan_with_gemini)

    result = await assistant.plan(
        "take off 10 meters",
        telemetry=_snapshot(),
        selected_target=None,
        grounding=_grounding(),
    )

    assert result.source == "gemini"
    assert [call.name for call in result.proposed_calls] == ["guided_takeoff"]


@pytest.mark.asyncio
async def test_dashboard_assistant_falls_back_when_gemini_errors(monkeypatch) -> None:
    assistant = DashboardAssistant(Settings(_env_file=None, gemini_api_key="test-key"))

    def fake_plan_with_gemini(*args, **kwargs):
        raise RuntimeError("Gemini unavailable")

    monkeypatch.setattr(assistant, "_plan_with_gemini", fake_plan_with_gemini)

    result = await assistant.plan(
        "orbit the selected target",
        telemetry=_snapshot(),
        selected_target=AssistantTarget(
            latitude_deg=46.2332,
            longitude_deg=6.0557,
            source="map",
        ),
        grounding=_grounding(),
    )

    assert result.source == "fallback"
    assert result.fallback_reason == "Gemini unavailable"
    assert [call.name for call in result.proposed_calls] == ["orbit"]
