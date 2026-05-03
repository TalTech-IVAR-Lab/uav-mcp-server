from __future__ import annotations

import pytest

from uav_mcp_server.assistant import (
    AssistantGroundingContext,
    AssistantTarget,
    AssistantToolCall,
    DashboardAssistant,
    _GeminiVisionTarget,
    _camera_target_from_gemini,
    _extract_json_payload,
    needs_camera_target_resolution,
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


def test_camera_target_resolution_only_triggers_for_visual_target_commands() -> None:
    assert needs_camera_target_resolution("orbit around the small building near the middle")
    assert needs_camera_target_resolution("approach the object behind the building")
    assert not needs_camera_target_resolution("take off to 10 meters")
    assert not needs_camera_target_resolution(
        "orbit selected target",
        selected_target=AssistantTarget(latitude_deg=46.0, longitude_deg=6.0),
    )


def test_camera_target_from_gemini_uses_bbox_footpoint_when_pixel_missing() -> None:
    target = _camera_target_from_gemini(
        _GeminiVisionTarget(
            found=True,
            label="small building",
            confidence=0.82,
            bbox_xyxy=[100.0, 40.0, 220.0, 160.0],
            selection_anchor="ground_footpoint",
        ),
        640,
        360,
    )

    assert target.found is True
    assert target.u == pytest.approx(160.0)
    assert target.v == pytest.approx(160.0)
    assert target.label == "small building"


@pytest.mark.asyncio
async def test_camera_target_locator_rejects_missing_api_key() -> None:
    assistant = DashboardAssistant(Settings(_env_file=None, gemini_api_key=None))

    with pytest.raises(RuntimeError, match="Gemini API key"):
        await assistant.locate_camera_target(
            "orbit around the building in the camera",
            image_jpeg=b"jpeg",
            image_width_px=640,
            image_height_px=360,
        )


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
async def test_dashboard_assistant_normalizes_orbit_yaw_aliases(monkeypatch) -> None:
    assistant = DashboardAssistant(Settings(_env_file=None, gemini_api_key="test-key"))

    def fake_plan_with_gemini(*args, **kwargs):
        return type(
            "GeminiResult",
            (),
            {
                "assistant_text": "Orbit while facing the target.",
                "calls": [
                    AssistantToolCall(
                        name="orbit",
                        arguments={
                            "latitude_deg": 46.2332,
                            "longitude_deg": 6.0557,
                            "absolute_altitude_m": 150.0,
                            "radius_m": 12.0,
                            "velocity_m_s": 3.0,
                            "yaw_behavior": "face_center",
                        },
                        summary="Orbit facing the center.",
                    )
                ],
            },
        )()

    monkeypatch.setattr(assistant, "_plan_with_gemini", fake_plan_with_gemini)

    result = await assistant.plan(
        "orbit the visible object",
        telemetry=_snapshot(),
        selected_target=AssistantTarget(latitude_deg=46.2332, longitude_deg=6.0557),
        grounding=_grounding(),
    )

    assert result.proposed_calls[0].arguments["yaw_behavior"] == "hold_front_to_circle_center"


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
