"""Optional camera ingestion and MJPEG streaming.

The primary path tries to use ROS2 in-process. When the server runs under a
Python runtime incompatible with the local ROS2 build, it falls back to a ROS2
helper subprocess using a configurable Python interpreter.
"""

from __future__ import annotations

import atexit
import asyncio
import logging
import os
import struct
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CameraStatus:
    enabled: bool
    available: bool
    topic: str
    fps: int
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "available": self.available,
            "topic": self.topic,
            "fps": self.fps,
            "reason": self.reason,
        }


class CameraStreamer:
    """Keeps the latest JPEG frame and exposes an MJPEG stream."""

    boundary = "frame"

    def __init__(
        self,
        *,
        enabled: bool,
        topic: str,
        fps: int,
        helper_python_bin: str = "python3.10",
        ros_setup_script: str = "/opt/ros/humble/setup.bash",
        helper_gazebo_topic_suffix: str = "/fpv_cam/link/camera/image",
    ) -> None:
        self._enabled = enabled
        self._topic = topic
        self._fps = max(1, fps)
        self._helper_python_bin = helper_python_bin
        self._ros_setup_script = ros_setup_script
        self._helper_gazebo_topic_suffix = helper_gazebo_topic_suffix
        self._latest_frame: bytes | None = None
        self._lock = threading.Lock()
        self._status = CameraStatus(enabled=enabled, available=False, topic=topic, fps=self._fps)
        self._thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._executor: Any | None = None
        self._node: Any | None = None
        self._rclpy: Any | None = None
        self._owns_rclpy_init = False
        self._last_frame_monotonic: float | None = None
        self._frame_stale_after_s = max(2.0, 3.0 / float(self._fps))

        if not enabled:
            self._status.reason = "Camera feature is disabled in settings."
            return

        atexit.register(self.close)

        if self._start_in_process_subscriber():
            return

        self._start_helper_subprocess()

    def get_frame(self) -> bytes | None:
        with self._lock:
            return self._latest_frame

    def is_available(self) -> bool:
        if self._process is not None and self._process.poll() is not None:
            self._status.available = False
            if self._status.reason is None:
                self._status.reason = (
                    f"Camera helper exited with status {self._process.returncode}."
                )
            return False

        if self._last_frame_monotonic is None:
            self._status.available = False
            if self._status.reason is None:
                self._status.reason = f"Waiting for frames on {self._topic}."
            return False

        if (time.monotonic() - self._last_frame_monotonic) > self._frame_stale_after_s:
            self._status.available = False
            self._status.reason = f"Camera frames are stale on {self._topic}."
            return False

        self._status.available = True
        return True

    def status(self) -> CameraStatus:
        self.is_available()
        return self._status

    def close(self) -> None:
        if self._process is not None:
            process = self._process
            self._process = None
            try:
                process.terminate()
            except Exception:
                pass
        self._teardown_in_process()

    async def stream_mjpeg(self) -> Any:
        frame_period_s = 1.0 / float(self._fps)
        while True:
            frame = self.get_frame()
            if frame is not None:
                headers = (
                    f"--{self.boundary}\r\n"
                    "Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(frame)}\r\n\r\n"
                ).encode("ascii")
                yield headers + frame + b"\r\n"
            await asyncio.sleep(frame_period_s)

    def _start_in_process_subscriber(self) -> bool:
        try:
            import cv2
            import numpy as np
            import rclpy
            from rclpy.executors import SingleThreadedExecutor
            from sensor_msgs.msg import Image
        except Exception as exc:
            logger.info("In-process camera support unavailable; falling back to helper: %s", exc)
            self._status.reason = f"In-process camera unavailable: {exc}"
            return False

        self._cv2 = cv2
        self._np = np
        self._Image = Image
        self._SingleThreadedExecutor = SingleThreadedExecutor
        self._rclpy = rclpy

        try:
            if not rclpy.ok():
                rclpy.init(args=None)
                self._owns_rclpy_init = True
            self._node = rclpy.create_node("uav_mcp_camera_streamer")
            self._node.create_subscription(Image, self._topic, self._on_image, 10)
            self._executor = SingleThreadedExecutor()
            self._executor.add_node(self._node)
            self._thread = threading.Thread(target=self._spin, daemon=True)
            self._thread.start()
            self._status.available = False
            self._status.reason = f"Waiting for frames on {self._topic}."
            return True
        except Exception as exc:
            logger.warning("In-process camera initialization failed: %s", exc)
            self._status.reason = f"In-process camera init failed: {exc}"
            self._teardown_in_process()
            return False

    def _start_helper_subprocess(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_root / "src") + (
            f":{env['PYTHONPATH']}" if env.get("PYTHONPATH") else ""
        )

        if Path(self._ros_setup_script).is_file():
            command = [
                "bash",
                "-lc",
                (
                    f"set -eo pipefail; "
                    f"source {self._shell_quote(self._ros_setup_script)}; "
                    f"export PYTHONPATH={self._shell_quote(str(repo_root / 'src'))}${{PYTHONPATH:+:$PYTHONPATH}}; "
                    f"exec {self._shell_quote(self._helper_python_bin)} "
                    f"-m uav_mcp_server.camera_worker "
                    f"--topic {self._shell_quote(self._topic)} "
                    f"--gazebo-topic-suffix {self._shell_quote(self._helper_gazebo_topic_suffix)}"
                ),
            ]
        else:
            command = [
                self._helper_python_bin,
                "-m",
                "uav_mcp_server.camera_worker",
                "--topic",
                self._topic,
                "--gazebo-topic-suffix",
                self._helper_gazebo_topic_suffix,
            ]

        try:
            process = subprocess.Popen(
                command,
                cwd=str(repo_root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except Exception as exc:
            logger.warning("Camera helper subprocess failed to start: %s", exc)
            self._status.reason = (
                f"Camera helper failed to start with {self._helper_python_bin}: {exc}"
            )
            return

        self._process = process
        self._thread = threading.Thread(target=self._read_helper_frames, daemon=True)
        self._thread.start()
        self._stderr_thread = threading.Thread(target=self._read_helper_stderr, daemon=True)
        self._stderr_thread.start()
        self._status.available = False
        self._status.reason = (
            f"Camera helper running via {self._helper_python_bin}; waiting for ROS2 frames on "
            f"{self._topic} or Gazebo camera transport frames matching "
            f"{self._helper_gazebo_topic_suffix}."
        )

    def _read_helper_frames(self) -> None:
        assert self._process is not None and self._process.stdout is not None
        stream = self._process.stdout
        try:
            while True:
                header = self._read_exact(stream, 4)
                if header is None:
                    break
                frame_length = struct.unpack(">I", header)[0]
                frame = self._read_exact(stream, frame_length)
                if frame is None:
                    break
                self._store_frame(frame, status_message=f"Camera streaming via {self._helper_python_bin}.")
        finally:
            self._status.available = False
            if self._process is not None:
                return_code = self._process.poll()
                self._status.reason = (
                    f"Camera helper stopped with status {return_code}."
                    if return_code is not None
                    else "Camera helper stopped."
                )

    def _read_helper_stderr(self) -> None:
        if self._process is None or self._process.stderr is None:
            return
        for raw_line in self._process.stderr:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if line:
                logger.info("camera-helper: %s", line)

    def _read_exact(self, stream: Any, size: int) -> bytes | None:
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = stream.read(remaining)
            if not chunk:
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _spin(self) -> None:
        try:
            if self._executor is not None:
                self._executor.spin()
        except Exception as exc:
            logger.warning("Camera ROS2 spin loop stopped: %s", exc)
            self._status.available = False
            self._status.reason = f"Camera spin loop stopped: {exc}"
        finally:
            self._teardown_in_process()

    def _on_image(self, message: Any) -> None:
        try:
            frame = self._message_to_jpeg(message)
        except Exception as exc:
            logger.debug("Camera frame dropped: %s", exc)
            return
        self._store_frame(frame, status_message="Camera subscriber streaming in-process.")

    def _store_frame(self, frame: bytes, *, status_message: str) -> None:
        with self._lock:
            self._latest_frame = frame
        self._last_frame_monotonic = time.monotonic()
        self._status.available = True
        self._status.reason = status_message

    def _message_to_jpeg(self, message: Any) -> bytes:
        channels_by_encoding = {
            "rgb8": 3,
            "bgr8": 3,
            "rgba8": 4,
            "bgra8": 4,
            "mono8": 1,
        }
        if message.encoding not in channels_by_encoding:
            raise ValueError(f"Unsupported camera encoding: {message.encoding}")

        channels = channels_by_encoding[message.encoding]
        array = self._np.frombuffer(message.data, dtype=self._np.uint8)
        if channels == 1:
            image = array.reshape((message.height, message.step))[:, : message.width]
        else:
            image = array.reshape((message.height, message.step // channels, channels))[
                :, : message.width, :
            ]

        if message.encoding == "rgb8":
            image = self._cv2.cvtColor(image, self._cv2.COLOR_RGB2BGR)
        elif message.encoding == "rgba8":
            image = self._cv2.cvtColor(image, self._cv2.COLOR_RGBA2BGR)
        elif message.encoding == "bgra8":
            image = self._cv2.cvtColor(image, self._cv2.COLOR_BGRA2BGR)

        ok, encoded = self._cv2.imencode(
            ".jpg",
            image,
            [int(self._cv2.IMWRITE_JPEG_QUALITY), 85],
        )
        if not ok:
            raise RuntimeError("OpenCV failed to encode camera frame.")
        return encoded.tobytes()

    def _teardown_in_process(self) -> None:
        executor = self._executor
        self._executor = None
        if executor is not None:
            try:
                executor.shutdown()
            except Exception:
                pass

        node = self._node
        self._node = None
        if node is not None:
            try:
                node.destroy_node()
            except Exception:
                pass

        if self._owns_rclpy_init and self._rclpy is not None:
            try:
                self._rclpy.shutdown()
            except Exception:
                pass
            finally:
                self._owns_rclpy_init = False

    def _shell_quote(self, value: str) -> str:
        return "'" + value.replace("'", "'\"'\"'") + "'"
