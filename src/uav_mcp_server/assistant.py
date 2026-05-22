"""Assistant planning and fallback parsing for the operator dashboard."""

from __future__ import annotations

import json
import logging
import os
import random
import re
import time
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from uav_mcp_server.config import Settings
from uav_mcp_server.navigation import coordinate_offset_m
from uav_mcp_server.types import OrbitYawBehavior, TelemetrySnapshot

_LOG = logging.getLogger(__name__)

# Gemini transient-failure markers. Match string-side rather than against a
# concrete exception class because the google-genai SDK packages errors
# under several different class names across versions, but the substring
# "503" / "UNAVAILABLE" / "429" / "RESOURCE_EXHAUSTED" / "deadline" stays
# stable in the exception payload.
_GEMINI_RETRYABLE_MARKERS = (
    "503",
    "unavailable",
    "429",
    "resource_exhausted",
    "rate limit",
    "deadline",
    "timeout",
    "internal error",
    "500 internal",
    "502 bad gateway",
    "504 gateway timeout",
)


def _is_retryable_gemini_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _GEMINI_RETRYABLE_MARKERS)


def _generate_with_retry(
    client: Any,
    *,
    model: str,
    contents: Any,
    config: Any,
    max_attempts: int = 4,
    base_delay_s: float = 1.0,
    max_delay_s: float = 8.0,
) -> Any:
    """Call ``client.models.generate_content`` with exponential backoff.

    Retries on transient Gemini errors (503, 429, 5xx, timeouts) up to
    ``max_attempts`` times with delays ``base * 2**attempt + jitter``,
    capped at ``max_delay_s``. Non-transient errors (400, 401, 403, 404,
    invalid argument, schema errors) propagate immediately so callers can
    fall back to the local planner without wasting time retrying.
    """
    last_exc: BaseException | None = None
    for attempt in range(max_attempts):
        try:
            return client.models.generate_content(
                model=model, contents=contents, config=config,
            )
        except Exception as exc:  # noqa: BLE001 — google-genai exception hierarchy varies
            last_exc = exc
            if not _is_retryable_gemini_error(exc):
                raise
            if attempt == max_attempts - 1:
                _LOG.warning(
                    "Gemini retry budget exhausted after %d attempts: %s",
                    max_attempts, exc,
                )
                raise
            delay = min(base_delay_s * (2 ** attempt), max_delay_s) + random.uniform(0.0, 0.4)
            _LOG.info(
                "Gemini transient error (attempt %d/%d), retrying in %.1fs: %s",
                attempt + 1, max_attempts, delay, exc,
            )
            time.sleep(delay)
    # Unreachable, but mypy / static analysis appreciate it.
    assert last_exc is not None
    raise last_exc

READ_ONLY_COMMANDS = frozenset({"get_status", "get_telemetry"})
ASSISTANT_ALLOWED_COMMANDS = frozenset(
    {
        "connect",
        "arm",
        "disarm",
        "guided_takeoff",
        "hold",
        "rtl",
        "land",
        "goto_relative",
        "orbit",
        "get_status",
        "get_telemetry",
    }
)


class AssistantToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""


class AssistantTarget(BaseModel):
    source: str = "map"
    latitude_deg: float
    longitude_deg: float
    absolute_altitude_m: float | None = None
    north_m: float | None = None
    east_m: float | None = None
    distance_m: float | None = None
    label: str | None = None


class AssistantCameraTarget(BaseModel):
    found: bool
    label: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    u: float | None = None
    v: float | None = None
    bbox_xyxy: list[float] | None = None
    selection_anchor: str = "ground_footpoint"
    rationale: str = ""


class AssistantPlan(BaseModel):
    source: str
    operator_text: str
    assistant_text: str
    requires_confirmation: bool
    proposed_calls: list[AssistantToolCall] = Field(default_factory=list)
    fallback_reason: str | None = None


class _GeminiPlan(BaseModel):
    assistant_text: str
    calls: list[AssistantToolCall] = Field(default_factory=list)


class _GeminiVisionTarget(BaseModel):
    found: bool = False
    label: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    # Pixel-space coordinates the model claims are in the original image's
    # coordinate system. Gemini Vision is known to return these in its
    # internal resized preprocess space when the model "forgets" the input
    # resolution, so we also accept normalised [0, 1] coords and prefer
    # those when they're populated — those are dimension-agnostic by
    # construction.
    u: float | None = None
    v: float | None = None
    # Normalised [0.0, 1.0] coordinates — independent of image dimensions.
    # When Gemini provides these we use them in preference to u/v so any
    # internal-resolution drift is naturally cancelled out.
    u_norm: float | None = None
    v_norm: float | None = None
    bbox_xyxy: list[float] | None = None
    bbox_norm: list[float] | None = None
    selection_anchor: str | None = None
    rationale: str = ""


class AssistantGroundingContext(BaseModel):
    source: str = "local"
    command_manifest: list[dict[str, Any]] = Field(default_factory=list)
    server_instructions: str = ""
    workflow_guide: str = ""
    operator_prompt: str = ""
    safety_config: dict[str, Any] = Field(default_factory=dict)


def workflow_guide_text(settings: Settings) -> str:
    return (
        "Use guided_takeoff for normal launch requests such as 'take off to 50 meters'. "
        "guided_takeoff may connect and arm first when needed. "
        "Use arm only when the operator explicitly wants arming without takeoff. "
        "Use takeoff only for low-level armed takeoff flows; prefer guided_takeoff in normal language. "
        "Use goto_relative for bounded relative movement. "
        "Use orbit only when there is an explicit target position. "
        "Use hold, rtl, and land for recovery workflows. "
        "Never invent unsupported commands, never bypass safety, and never execute more than 4 tool calls in one turn. "
        f"Altitude must stay within {settings.min_altitude_m:.1f} m and {settings.max_altitude_m:.1f} m. "
        f"Orbit radius must stay within {settings.min_orbit_radius_m:.1f} m and {settings.max_orbit_radius_m:.1f} m."
    )


def operator_prompt_text() -> str:
    return (
        "You are the UAV operator copilot. Translate the operator request into explicit tool calls. "
        "Prefer the smallest safe action sequence. For state-changing actions, summarize what will happen plainly. "
        "If the request is ambiguous or unsupported, return no tool calls and explain the gap briefly."
    )


_CAMERA_TARGET_ACTION_RE = re.compile(
    r"\b(orbit|circle|approach|inspect|look at|go to|goto|track|follow)\b",
    re.IGNORECASE,
)
_CAMERA_TARGET_CUE_RE = re.compile(
    r"\b("
    r"camera|image|video|feed|frame|screen|reticle|middle|center|centre|left|right|top|"
    r"bottom|front|behind|near|visible|building|object|target|car|vehicle|person|tree"
    r")\b",
    re.IGNORECASE,
)


def needs_camera_target_resolution(
    operator_text: str,
    *,
    selected_target: AssistantTarget | None = None,
) -> bool:
    if selected_target is not None:
        return False
    normalized = operator_text.strip()
    if not normalized:
        return False
    return bool(_CAMERA_TARGET_ACTION_RE.search(normalized) and _CAMERA_TARGET_CUE_RE.search(normalized))


def _normalize_calls(calls: list[AssistantToolCall]) -> list[AssistantToolCall]:
    normalized: list[AssistantToolCall] = []
    for call in calls[:4]:
        if call.name not in ASSISTANT_ALLOWED_COMMANDS:
            raise ValueError(f"Command '{call.name}' is not allowed in dashboard assistant mode.")
        if not isinstance(call.arguments, dict):
            raise ValueError(f"Command '{call.name}' arguments must be an object.")
        arguments = dict(call.arguments)
        if call.name == "orbit" and isinstance(arguments.get("yaw_behavior"), str):
            arguments["yaw_behavior"] = OrbitYawBehavior.parse(arguments["yaw_behavior"]).value
        normalized.append(
            AssistantToolCall(
                name=call.name,
                arguments=arguments,
                summary=call.summary or call.name.replace("_", " "),
            )
        )
    return normalized


def _requires_confirmation(calls: list[AssistantToolCall]) -> bool:
    return any(call.name not in READ_ONLY_COMMANDS for call in calls)


def _target_orbit_call(
    target: AssistantTarget,
    snapshot: TelemetrySnapshot,
    settings: Settings,
    *,
    radius_m: float | None = None,
    velocity_m_s: float | None = None,
) -> AssistantToolCall:
    absolute_altitude_m = target.absolute_altitude_m or snapshot.absolute_altitude_m
    if absolute_altitude_m is None:
        home_absolute_altitude_m = snapshot.inferred_home_absolute_altitude_m()
        if home_absolute_altitude_m is not None:
            absolute_altitude_m = home_absolute_altitude_m + settings.default_takeoff_altitude_m
    if absolute_altitude_m is None:
        raise ValueError("Current altitude is unavailable; orbit target altitude cannot be resolved.")
    resolved_radius = radius_m or max(settings.min_orbit_radius_m, 12.0)
    resolved_velocity = velocity_m_s or min(settings.default_mission_speed_m_s, 3.0)
    return AssistantToolCall(
        name="orbit",
        arguments={
            "latitude_deg": target.latitude_deg,
            "longitude_deg": target.longitude_deg,
            "absolute_altitude_m": absolute_altitude_m,
            "radius_m": resolved_radius,
            "velocity_m_s": resolved_velocity,
        },
        summary=(
            f"Orbit target at {target.latitude_deg:.6f}, {target.longitude_deg:.6f} "
            f"from the current operating altitude."
        ),
    )


def _target_approach_call(
    target: AssistantTarget,
    snapshot: TelemetrySnapshot,
    settings: Settings,
) -> AssistantToolCall:
    north_m = target.north_m
    east_m = target.east_m
    if north_m is None or east_m is None:
        if snapshot.latitude_deg is None or snapshot.longitude_deg is None:
            raise ValueError("Current position is unavailable; cannot compute an approach vector.")
        north_m, east_m = coordinate_offset_m(
            snapshot.latitude_deg,
            snapshot.longitude_deg,
            target.latitude_deg,
            target.longitude_deg,
        )
    altitude_m = snapshot.relative_altitude_m or settings.default_takeoff_altitude_m
    return AssistantToolCall(
        name="goto_relative",
        arguments={
            "north_m": north_m,
            "east_m": east_m,
            "altitude_m": altitude_m,
        },
        summary="Approach the selected target while holding the current altitude.",
    )


def fallback_plan(
    operator_text: str,
    *,
    settings: Settings,
    telemetry: TelemetrySnapshot,
    selected_target: AssistantTarget | None = None,
) -> AssistantPlan:
    normalized = operator_text.strip().lower()
    calls: list[AssistantToolCall] = []
    if not normalized:
        return AssistantPlan(
            source="fallback",
            operator_text=operator_text,
            assistant_text="No command text was provided.",
            requires_confirmation=False,
            proposed_calls=[],
        )

    if re.search(r"\b(status|state|mode)\b", normalized):
        calls = [AssistantToolCall(name="get_status", summary="Fetch the current vehicle status.")]
    elif re.search(r"\b(telemetry|position|battery)\b", normalized):
        calls = [AssistantToolCall(name="get_telemetry", summary="Fetch the latest telemetry snapshot.")]
    elif "connect" in normalized:
        calls = [AssistantToolCall(name="connect", summary="Connect to the active flight backend.")]
    elif "disarm" in normalized:
        calls = [AssistantToolCall(name="disarm", summary="Disarm the vehicle.")]
    elif re.search(r"\barm\b", normalized):
        calls = [AssistantToolCall(name="arm", summary="Arm the vehicle after preflight checks.")]
    elif re.search(r"\bland\b", normalized):
        calls = [AssistantToolCall(name="land", summary="Land the vehicle.")]
    elif re.search(r"\b(rtl|return|come back)\b", normalized):
        calls = [AssistantToolCall(name="rtl", summary="Return to launch.")]
    elif re.search(r"\b(hold|hover|stop)\b", normalized):
        calls = [AssistantToolCall(name="hold", summary="Hold the current position.")]
    else:
        takeoff_match = re.search(r"take\s*off(?:\s+to)?\s+(\d+(?:\.\d+)?)?", normalized)
        goto_match = re.search(
            r"go\s+(north|south|east|west)\s+(\d+(?:\.\d+)?)\s*(?:meter|meters|m)?",
            normalized,
        )
        orbit_match = re.search(r"\b(circle|orbit)\b", normalized)
        approach_match = re.search(r"\b(approach|inspect|go to target)\b", normalized)

        if takeoff_match:
            altitude = (
                float(takeoff_match.group(1))
                if takeoff_match.group(1)
                else settings.default_takeoff_altitude_m
            )
            calls = [
                AssistantToolCall(
                    name="guided_takeoff",
                    arguments={"altitude_m": altitude},
                    summary=f"Connect if needed, arm if needed, and take off to {altitude:.1f} m.",
                )
            ]
        elif goto_match:
            direction = goto_match.group(1)
            distance = float(goto_match.group(2))
            north_m = 0.0
            east_m = 0.0
            if direction == "north":
                north_m = distance
            elif direction == "south":
                north_m = -distance
            elif direction == "east":
                east_m = distance
            elif direction == "west":
                east_m = -distance
            altitude_m = telemetry.relative_altitude_m or settings.default_takeoff_altitude_m
            calls = [
                AssistantToolCall(
                    name="goto_relative",
                    arguments={
                        "north_m": north_m,
                        "east_m": east_m,
                        "altitude_m": altitude_m,
                    },
                    summary=f"Move {direction} by {distance:.1f} m at the current altitude.",
                )
            ]
        elif orbit_match and selected_target is not None:
            calls = [_target_orbit_call(selected_target, telemetry, settings)]
        elif approach_match and selected_target is not None:
            calls = [_target_approach_call(selected_target, telemetry, settings)]

    if calls:
        return AssistantPlan(
            source="fallback",
            operator_text=operator_text,
            assistant_text="Parsed the operator request with the local dashboard fallback planner.",
            requires_confirmation=_requires_confirmation(calls),
            proposed_calls=calls,
        )

    missing_target = (
        " Select a camera or map target first for orbit and target-approach requests."
        if re.search(r"\b(circle|orbit|approach|inspect|target)\b", normalized)
        else ""
    )
    return AssistantPlan(
        source="fallback",
        operator_text=operator_text,
        assistant_text=f"The fallback parser could not safely map that request to a supported command.{missing_target}",
        requires_confirmation=False,
        proposed_calls=[],
    )


class DashboardAssistant:
    """Gemini-first planner with a deterministic local fallback."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.assistant_enabled

    @property
    def api_available(self) -> bool:
        return bool(self._settings.gemini_api_key or os.getenv("GEMINI_API_KEY"))

    async def plan(
        self,
        operator_text: str,
        *,
        telemetry: TelemetrySnapshot,
        selected_target: AssistantTarget | None,
        grounding: AssistantGroundingContext,
    ) -> AssistantPlan:
        fallback_reason: str | None = None
        if self.enabled and self.api_available:
            try:
                gemini_plan = self._plan_with_gemini(
                    operator_text,
                    telemetry=telemetry,
                    selected_target=selected_target,
                    grounding=grounding,
                )
                calls = _normalize_calls(gemini_plan.calls)
                return AssistantPlan(
                    source="gemini",
                    operator_text=operator_text,
                    assistant_text=gemini_plan.assistant_text,
                    requires_confirmation=_requires_confirmation(calls),
                    proposed_calls=calls,
                )
            except Exception as exc:
                # Surface a tidy reason for the dashboard chat trail. The
                # retry helper already burned the retry budget on transient
                # errors; if we reach here on a transient marker it means
                # all attempts failed, so the message reflects "after
                # retries" instead of just dumping the raw payload.
                if _is_retryable_gemini_error(exc):
                    fallback_reason = (
                        f"Gemini overloaded after "
                        f"{self._settings.assistant_max_retries} retries — "
                        f"used local fallback planner. ({exc})"
                    )
                else:
                    fallback_reason = str(exc)
                _LOG.warning("Assistant plan via Gemini failed: %s", exc)

        fallback = fallback_plan(
            operator_text,
            settings=self._settings,
            telemetry=telemetry,
            selected_target=selected_target,
        )
        if fallback_reason is not None:
            fallback.fallback_reason = fallback_reason
        return fallback

    async def locate_camera_target(
        self,
        operator_text: str,
        *,
        image_jpeg: bytes,
        image_width_px: int,
        image_height_px: int,
    ) -> AssistantCameraTarget:
        if not self.enabled:
            raise RuntimeError("Assistant is disabled; camera target analysis is unavailable.")
        if not self._settings.assistant_vision_enabled:
            raise RuntimeError("Assistant vision is disabled in settings.")
        if not self.api_available:
            raise RuntimeError("Gemini API key is not configured; camera target analysis is unavailable.")
        return await self._locate_camera_target_with_gemini(
            operator_text,
            image_jpeg=image_jpeg,
            image_width_px=image_width_px,
            image_height_px=image_height_px,
        )

    async def _locate_camera_target_with_gemini(
        self,
        operator_text: str,
        *,
        image_jpeg: bytes,
        image_width_px: int,
        image_height_px: int,
    ) -> AssistantCameraTarget:
        import asyncio

        return await asyncio.to_thread(
            self._locate_camera_target_with_gemini_sync,
            operator_text,
            image_jpeg=image_jpeg,
            image_width_px=image_width_px,
            image_height_px=image_height_px,
        )

    def _locate_camera_target_with_gemini_sync(
        self,
        operator_text: str,
        *,
        image_jpeg: bytes,
        image_width_px: int,
        image_height_px: int,
    ) -> AssistantCameraTarget:
        from google import genai
        from google.genai import types

        # Verify the JPEG bytes actually have the dimensions the caller
        # claims. If they differ (a downsampled / resized frame slipping
        # through the pipeline), use the JPEG-encoded dimensions for the
        # prompt and capture the scale factor — we'll un-scale Gemini's
        # pixel coords back to the projection layer's coordinate system
        # before returning.
        actual_w, actual_h = _decode_jpeg_dimensions(image_jpeg)
        if actual_w is not None and actual_h is not None and (
            actual_w != image_width_px or actual_h != image_height_px
        ):
            _LOG.warning(
                "Camera frame dimensions (%dx%d) disagree with camera_params "
                "(%dx%d). Telling Gemini the actual frame dimensions and "
                "rescaling its pixel coords back to camera_params space.",
                actual_w, actual_h, image_width_px, image_height_px,
            )
            prompt_w, prompt_h = actual_w, actual_h
        else:
            prompt_w, prompt_h = image_width_px, image_height_px

        client = genai.Client(api_key=self._settings.gemini_api_key or os.getenv("GEMINI_API_KEY"))
        prompt_payload = {
            "task": "Locate the single visual target in the current drone camera frame.",
            "operator_request": operator_text,
            "image_width_px": prompt_w,
            "image_height_px": prompt_h,
            "instructions": [
                "Return only JSON.",
                f"The image is exactly {prompt_w} pixels wide and {prompt_h} pixels tall.",
                "Provide both pixel coordinates (u, v) AND normalised coordinates "
                "(u_norm, v_norm) in the [0.0, 1.0] range. u_norm = u / width, "
                "v_norm = v / height. The normalised values are what downstream "
                "consumers rely on, so they must be precise.",
                "Origin is the TOP-LEFT corner of the image. u (or u_norm) "
                "increases to the right, v (or v_norm) increases downward.",
                "If the target is a ground object or building, return the "
                "bottom-center footpoint of the visible target — where the "
                "object touches the ground — NOT the visual centroid. This "
                "matters because downstream projection uses this point to "
                "intersect the ground plane.",
                "If the operator refers to an object behind or near another "
                "object, choose the most likely visible target satisfying that "
                "spatial relation.",
                "If the target is not visible or ambiguous, set found=false "
                "and do not guess.",
            ],
            "required_json_shape": {
                "found": "boolean",
                "label": "short target label or null",
                "confidence": "0.0 to 1.0",
                "u": "target pixel x coordinate (0..width-1), null if not found",
                "v": "target pixel y coordinate (0..height-1), null if not found",
                "u_norm": "u / width, 0.0..1.0, null if not found",
                "v_norm": "v / height, 0.0..1.0, null if not found",
                "bbox_xyxy": "[left, top, right, bottom] in pixels, null if unavailable",
                "bbox_norm": "[left, top, right, bottom] normalised 0..1, null if unavailable",
                "selection_anchor": "ground_footpoint, object_center, or clicked_pixel",
                "rationale": "one short sentence",
            },
        }
        image_part = _gemini_image_part(types, image_jpeg, "image/jpeg")
        response = _generate_with_retry(
            client,
            model=self._settings.assistant_model,
            contents=[json.dumps(prompt_payload, ensure_ascii=True), image_part],
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are a precise UAV visual target localizer. You do not command the UAV; "
                    "you only identify the requested target pixel for downstream calibrated projection."
                ),
                temperature=0.0,
                response_mime_type="application/json",
            ),
            max_attempts=self._settings.assistant_max_retries,
            base_delay_s=self._settings.assistant_retry_base_delay_s,
            max_delay_s=self._settings.assistant_retry_max_delay_s,
        )
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty camera target response.")
        raw = _GeminiVisionTarget.model_validate(_extract_json_payload(text))
        return _camera_target_from_gemini(raw, image_width_px, image_height_px)

    def _plan_with_gemini(
        self,
        operator_text: str,
        *,
        telemetry: TelemetrySnapshot,
        selected_target: AssistantTarget | None,
        grounding: AssistantGroundingContext,
    ) -> _GeminiPlan:
        from google import genai

        client = genai.Client(api_key=self._settings.gemini_api_key or os.getenv("GEMINI_API_KEY"))
        tool_summary = [
            {
                "name": command["name"],
                "label": command.get("label"),
                "hint": command.get("hint"),
                "params": command.get("params", []),
                "required_params": command.get("required_params", []),
            }
            for command in grounding.command_manifest
            if command.get("name") in ASSISTANT_ALLOWED_COMMANDS
        ]
        prompt_payload = {
            "operator_request": operator_text,
            "telemetry": telemetry.model_dump(mode="json"),
            "selected_target": selected_target.model_dump(mode="json") if selected_target else None,
            "tools": tool_summary,
            "workflow_guide": grounding.workflow_guide or workflow_guide_text(self._settings),
            "operator_prompt": grounding.operator_prompt or operator_prompt_text(),
            "safety_config": grounding.safety_config,
            "required_json_shape": {
                "assistant_text": "short plain-language summary",
                "calls": [
                    {
                        "name": "tool name from the provided list",
                        "arguments": {"parameter": "value"},
                        "summary": "short explanation of the call",
                    }
                ],
            },
        }
        response = _generate_with_retry(
            client,
            model=self._settings.assistant_model,
            contents=json.dumps(prompt_payload, ensure_ascii=True),
            config=genai.types.GenerateContentConfig(
                system_instruction=grounding.server_instructions or operator_prompt_text(),
                temperature=self._settings.assistant_temperature,
                response_mime_type="application/json",
            ),
            max_attempts=self._settings.assistant_max_retries,
            base_delay_s=self._settings.assistant_retry_base_delay_s,
            max_delay_s=self._settings.assistant_retry_max_delay_s,
        )
        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response.")
        return _GeminiPlan.model_validate(_extract_json_payload(text))


def _extract_json_payload(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return json.loads(stripped)


def _gemini_image_part(types_module: Any, image_bytes: bytes, mime_type: str) -> Any:
    part_type = getattr(types_module, "Part")
    if hasattr(part_type, "from_bytes"):
        return part_type.from_bytes(data=image_bytes, mime_type=mime_type)
    blob_type = getattr(types_module, "Blob")
    return part_type(inline_data=blob_type(mime_type=mime_type, data=image_bytes))


def _camera_target_from_gemini(
    raw: _GeminiVisionTarget,
    image_width_px: int,
    image_height_px: int,
) -> AssistantCameraTarget:
    if not raw.found:
        return AssistantCameraTarget(
            found=False,
            label=raw.label,
            confidence=raw.confidence,
            rationale=raw.rationale,
        )

    anchor = raw.selection_anchor or "ground_footpoint"
    fw = float(image_width_px)
    fh = float(image_height_px)

    # Coordinate precedence (most → least trusted):
    #   1. normalised u_norm/v_norm   → rescale to (fw, fh). Dimension-
    #      independent, immune to Gemini's internal preprocess drift.
    #   2. raw pixel u/v              → trust only if it falls inside the
    #      image bounds.
    #   3. bounding-box centre        → fallback when explicit point is
    #      missing.
    u: float | None = None
    v: float | None = None
    coord_source = "none"

    if raw.u_norm is not None and raw.v_norm is not None:
        u = float(raw.u_norm) * fw
        v = float(raw.v_norm) * fh
        coord_source = "u_norm"
    elif raw.u is not None and raw.v is not None:
        u = float(raw.u)
        v = float(raw.v)
        coord_source = "u_px"

    # Bounding-box anchored fallback / refinement.
    bbox_px = raw.bbox_xyxy
    if (
        bbox_px is None
        and raw.bbox_norm is not None
        and len(raw.bbox_norm) == 4
    ):
        nl, nt, nr, nb = raw.bbox_norm
        bbox_px = [nl * fw, nt * fh, nr * fw, nb * fh]

    if (u is None or v is None) and bbox_px is not None and len(bbox_px) == 4:
        left, top, right, bottom = bbox_px
        if u is None:
            u = (left + right) / 2.0
        if v is None:
            v = bottom if anchor == "ground_footpoint" else (top + bottom) / 2.0
        coord_source = "bbox"

    if u is None or v is None:
        return AssistantCameraTarget(
            found=False,
            label=raw.label,
            confidence=raw.confidence,
            rationale="Vision model did not return usable pixel coordinates.",
        )

    clamped_u = max(0.0, min(fw, u))
    clamped_v = max(0.0, min(fh, v))
    _LOG.info(
        "Gemini vision target: source=%s u=%.1f v=%.1f → clamped=(%.1f, %.1f) "
        "in %dx%d (raw_u=%s raw_v=%s u_norm=%s v_norm=%s anchor=%s label=%s)",
        coord_source, u, v, clamped_u, clamped_v, image_width_px, image_height_px,
        raw.u, raw.v, raw.u_norm, raw.v_norm, anchor, raw.label,
    )
    return AssistantCameraTarget(
        found=True,
        label=raw.label,
        confidence=raw.confidence,
        u=clamped_u,
        v=clamped_v,
        bbox_xyxy=bbox_px,
        selection_anchor=anchor,
        rationale=raw.rationale,
    )


def _decode_jpeg_dimensions(image_jpeg: bytes) -> tuple[int | None, int | None]:
    """Return (width, height) of a JPEG byte string, or (None, None) on
    failure. Uses Pillow when available; gracefully degrades to None when
    the dependency isn't present so the existing best-effort flow keeps
    working."""
    try:
        from io import BytesIO
        from PIL import Image
    except Exception:  # noqa: BLE001
        return None, None
    try:
        with Image.open(BytesIO(image_jpeg)) as img:
            return int(img.width), int(img.height)
    except Exception:  # noqa: BLE001
        return None, None


def _resource_payload(resource: Any) -> Any:
    if hasattr(resource, "content") and getattr(resource, "content") is not None:
        return getattr(resource, "content")
    if hasattr(resource, "text") and getattr(resource, "text") is not None:
        return getattr(resource, "text")
    if hasattr(resource, "blob") and getattr(resource, "blob") is not None:
        return getattr(resource, "blob")
    if hasattr(resource, "model_dump"):
        dumped = resource.model_dump(mode="json")
        if "content" in dumped:
            return dumped["content"]
        if "text" in dumped:
            return dumped["text"]
        if "blob" in dumped:
            return dumped["blob"]
        return dumped
    return resource


def _resource_text(resources: Sequence[Any]) -> str:
    parts: list[str] = []
    for resource in resources:
        payload = _resource_payload(resource)
        if isinstance(payload, (dict, list)):
            parts.append(json.dumps(payload, ensure_ascii=True, sort_keys=True))
        elif payload is not None:
            parts.append(str(payload))
    return "\n".join(part for part in parts if part).strip()


def _resource_dict(resources: Sequence[Any]) -> dict[str, Any]:
    for resource in resources:
        payload = _resource_payload(resource)
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, dict):
                return decoded
    return {}


def _prompt_text(messages: Sequence[Any]) -> str:
    parts: list[str] = []
    for message in messages:
        content = getattr(message, "content", None)
        text = getattr(content, "text", None)
        if text:
            parts.append(str(text).strip())
            continue
        if hasattr(content, "model_dump"):
            parts.append(json.dumps(content.model_dump(mode="json"), ensure_ascii=True, sort_keys=True))
            continue
        if content is not None:
            parts.append(str(content).strip())
    return "\n\n".join(part for part in parts if part).strip()


def build_command_manifest(tools: Sequence[Any]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for tool in tools:
        name = getattr(tool, "name", None)
        if not isinstance(name, str) or name not in ASSISTANT_ALLOWED_COMMANDS:
            continue
        schema = getattr(tool, "inputSchema", None) or getattr(tool, "input_schema", None) or {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        manifest.append(
            {
                "name": name,
                "label": getattr(tool, "title", None) or name,
                "hint": getattr(tool, "description", None) or "",
                "params": list(properties.keys()) if isinstance(properties, dict) else [],
                "required_params": list(schema.get("required", [])) if isinstance(schema, dict) else [],
            }
        )
    return manifest


async def fetch_mcp_grounding(url: str) -> AssistantGroundingContext:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url, timeout=3.0, sse_read_timeout=5.0) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            initialize_result = await session.initialize()
            tools_result = await session.list_tools()
            await session.list_resources()
            await session.list_prompts()
            workflow_result = await session.read_resource("uav://guide/workflows")
            safety_result = await session.read_resource("uav://config/safety")
            prompt_result = await session.get_prompt("operator_workflow_brief")

    return AssistantGroundingContext(
        source="mcp_http",
        command_manifest=build_command_manifest(tools_result.tools),
        server_instructions=getattr(initialize_result, "instructions", "") or "",
        workflow_guide=_resource_text(workflow_result.contents),
        operator_prompt=_prompt_text(prompt_result.messages),
        safety_config=_resource_dict(safety_result.contents),
    )
