"""Camera bridge worker for ROS2 or Gazebo Classic image transport."""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class RosCameraWorker:
    def __init__(self, topic: str) -> None:
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from sensor_msgs.msg import Image

        self._rclpy = rclpy
        self._executor_cls = SingleThreadedExecutor
        self._image_type = Image
        self._topic = topic
        self._node = None
        self._executor = None
        self._first_frame_at: float | None = None

    @property
    def got_first_frame(self) -> bool:
        return self._first_frame_at is not None

    def start(self) -> None:
        self._rclpy.init(args=None)
        self._node = self._rclpy.create_node("uav_mcp_camera_worker")
        self._node.create_subscription(self._image_type, self._topic, self._on_image, 10)
        self._executor = self._executor_cls()
        self._executor.add_node(self._node)
        logger.info("Subscribed to ROS2 camera topic %s", self._topic)

    def spin_until_first_frame(self, timeout_s: float) -> bool:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.got_first_frame:
                return True
            self._executor.spin_once(timeout_sec=0.1)
        return self.got_first_frame

    def spin_forever(self) -> None:
        while True:
            self._executor.spin_once(timeout_sec=0.1)

    def close(self) -> None:
        if self._executor is not None:
            try:
                self._executor.shutdown()
            except Exception:
                pass
            self._executor = None
        if self._node is not None:
            try:
                self._node.destroy_node()
            except Exception:
                pass
            self._node = None
        try:
            if self._rclpy.ok():
                self._rclpy.shutdown()
        except Exception:
            pass

    def _write_jpeg(self, frame: np.ndarray) -> None:
        ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if not ok:
            raise RuntimeError("OpenCV failed to encode camera frame.")
        payload = encoded.tobytes()
        sys.stdout.buffer.write(len(payload).to_bytes(4, "big"))
        sys.stdout.buffer.write(payload)
        sys.stdout.buffer.flush()

    def _on_image(self, message) -> None:
        try:
            frame = self._message_to_bgr(message)
            self._write_jpeg(frame)
            if self._first_frame_at is None:
                self._first_frame_at = time.monotonic()
        except Exception as exc:
            logger.debug("Dropped ROS2 camera frame: %s", exc)

    def _message_to_bgr(self, message) -> np.ndarray:
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
        array = np.frombuffer(message.data, dtype=np.uint8)
        if channels == 1:
            image = array.reshape((message.height, message.step))[:, : message.width]
        else:
            image = array.reshape((message.height, message.step // channels, channels))[
                :, : message.width, :
            ]

        if message.encoding == "rgb8":
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        elif message.encoding == "rgba8":
            image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
        elif message.encoding == "bgra8":
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

        return image


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ROS2 or Gazebo Classic camera bridge worker")
    parser.add_argument("--topic", required=True, help="ROS2 image topic to subscribe to")
    parser.add_argument(
        "--gazebo-topic-suffix",
        default="/fpv_cam/link/camera/image",
        help="Gazebo Classic topic suffix to discover when ROS2 frames are absent",
    )
    parser.add_argument(
        "--ros-startup-timeout-s",
        type=float,
        default=2.0,
        help="How long to wait for the first ROS2 frame before falling back",
    )
    return parser


def discover_gazebo_topic(suffix: str) -> str:
    result = subprocess.run(
        ["gz", "topic", "-l"],
        capture_output=True,
        text=True,
        check=True,
    )
    candidates = [line.strip() for line in result.stdout.splitlines() if line.strip().endswith(suffix)]
    if not candidates:
        raise RuntimeError(f"No Gazebo topic found matching suffix {suffix!r}.")
    return sorted(candidates)[0]


def exec_gazebo_bridge(topic_suffix: str) -> None:
    topic = discover_gazebo_topic(topic_suffix)
    repo_root = Path(__file__).resolve().parents[2]
    bridge_script = repo_root / "scripts" / "run_gazebo_camera_bridge.sh"
    logger.info("Falling back to Gazebo camera transport topic %s", topic)
    os.execv(str(bridge_script), [str(bridge_script), "--topic", topic])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
    parser = build_parser()
    args = parser.parse_args()

    try:
        ros_worker = RosCameraWorker(args.topic)
        ros_worker.start()
    except Exception as exc:
        logger.info("ROS2 camera worker unavailable: %s", exc)
        exec_gazebo_bridge(args.gazebo_topic_suffix)
        return

    try:
        if ros_worker.spin_until_first_frame(max(0.1, args.ros_startup_timeout_s)):
            logger.info("ROS2 camera stream active on %s", args.topic)
            ros_worker.spin_forever()
            return
        logger.info(
            "No ROS2 frames arrived on %s within %.1fs; falling back to Gazebo transport.",
            args.topic,
            args.ros_startup_timeout_s,
        )
    finally:
        ros_worker.close()

    exec_gazebo_bridge(args.gazebo_topic_suffix)


if __name__ == "__main__":
    main()
