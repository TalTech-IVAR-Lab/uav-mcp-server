from __future__ import annotations

from uav_mcp_server.camera import CameraStreamer
from uav_mcp_server import camera as camera_module


def _fake_in_process_start(self: CameraStreamer) -> bool:
    self._status.available = False
    self._status.reason = f"Waiting for frames on {self._topic}."
    return True


def test_camera_streamer_waits_for_first_frame(monkeypatch) -> None:
    monkeypatch.setattr(CameraStreamer, "_start_in_process_subscriber", _fake_in_process_start)

    streamer = CameraStreamer(enabled=True, topic="/usb_cam/image_raw", fps=15)

    assert streamer.is_available() is False
    assert streamer.status().reason == "Waiting for frames on /usb_cam/image_raw."

    streamer._store_frame(b"jpeg", status_message="Camera subscriber streaming in-process.")

    assert streamer.is_available() is True
    assert streamer.status().reason == "Camera subscriber streaming in-process."


def test_camera_streamer_marks_stale_frames_unavailable(monkeypatch) -> None:
    now = {"value": 100.0}

    monkeypatch.setattr(CameraStreamer, "_start_in_process_subscriber", _fake_in_process_start)
    monkeypatch.setattr(camera_module.time, "monotonic", lambda: now["value"])

    streamer = CameraStreamer(enabled=True, topic="/usb_cam/image_raw", fps=15)
    streamer._store_frame(b"jpeg", status_message="Camera subscriber streaming in-process.")

    assert streamer.is_available() is True

    now["value"] += 3.0

    assert streamer.is_available() is False
    assert streamer.status().reason == "Camera frames are stale on /usb_cam/image_raw."
