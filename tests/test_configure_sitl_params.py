from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "configure_sitl_params.py"
MODULE_SPEC = importlib.util.spec_from_file_location("configure_sitl_params", MODULE_PATH)
assert MODULE_SPEC is not None
assert MODULE_SPEC.loader is not None
configure_sitl_params = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(configure_sitl_params)


class FakeState:
    def __init__(self, is_connected: bool) -> None:
        self.is_connected = is_connected


class FakeCore:
    def __init__(self, states: list[bool]) -> None:
        self._states = states

    async def connection_state(self):
        for is_connected in self._states:
            yield FakeState(is_connected)


class FakeParam:
    def __init__(self, current_value: float) -> None:
        self.current_value = current_value
        self.set_calls: list[float] = []

    async def get_param_float(self, name: str) -> float:
        assert name == "COM_DISARM_PRFLT"
        return self.current_value

    async def set_param_float(self, name: str, value: float) -> None:
        assert name == "COM_DISARM_PRFLT"
        self.current_value = value
        self.set_calls.append(value)


class FakeSystem:
    def __init__(self, states: list[bool], current_value: float = 10.0) -> None:
        self.core = FakeCore(states)
        self.param = FakeParam(current_value)
        self.connected_to: str | None = None
        self.stopped = False

    async def connect(self, system_address: str) -> None:
        self.connected_to = system_address

    def _stop_mavsdk_server(self) -> None:
        self.stopped = True


def test_normalize_system_address_maps_wildcard_udpin_to_udp() -> None:
    assert (
        configure_sitl_params.normalize_system_address("udpin://0.0.0.0:14540") == "udp://:14540"
    )
    assert (
        configure_sitl_params.normalize_system_address("udpin://127.0.0.1:14540")
        == "udp://127.0.0.1:14540"
    )
    assert configure_sitl_params.normalize_system_address("udpout://127.0.0.1:14580") == (
        "udpout://127.0.0.1:14580"
    )


@pytest.mark.asyncio
async def test_connect_system_retries_and_cleans_failed_attempts() -> None:
    first = FakeSystem([False])
    second = FakeSystem([True])
    systems = [first, second]

    drone = await configure_sitl_params.connect_system(
        "udpin://0.0.0.0:14540",
        timeout_s=0.2,
        attempt_timeout_s=0.01,
        retry_interval_s=0.0,
        system_factory=lambda: systems.pop(0),
    )

    assert drone is second
    assert first.stopped is True
    assert second.stopped is False
    assert first.connected_to == "udp://:14540"
    assert second.connected_to == "udp://:14540"


@pytest.mark.asyncio
async def test_run_sets_param_and_stops_mavsdk_server(monkeypatch: pytest.MonkeyPatch) -> None:
    drone = FakeSystem([True], current_value=10.0)

    async def fake_connect_system(system_address: str, timeout_s: float):
        assert system_address == "udpin://0.0.0.0:14540"
        assert timeout_s == 30.0
        return drone

    monkeypatch.setattr(configure_sitl_params, "connect_system", fake_connect_system)

    await configure_sitl_params.run(
        argparse.Namespace(
            system_address="udpin://0.0.0.0:14540",
            preflight_auto_disarm_s=60.0,
            timeout_s=30.0,
        )
    )

    assert drone.param.set_calls == [60.0]
    assert drone.param.current_value == 60.0
    assert drone.stopped is True
