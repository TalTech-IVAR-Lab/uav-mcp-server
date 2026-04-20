from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "resolve_desktop_session_env.py"
)
SPEC = importlib.util.spec_from_file_location("resolve_desktop_session_env", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_choose_desktop_session_env_prefers_existing_xauthority(monkeypatch) -> None:
    def fake_exists(path: str) -> bool:
        return path == "/run/user/1000/.mutter-Xwaylandauth.valid"

    def fake_isdir(path: str) -> bool:
        return path == "/run/user/1000"

    monkeypatch.setattr(MODULE.os.path, "exists", fake_exists)
    monkeypatch.setattr(MODULE.os.path, "isdir", fake_isdir)

    resolved = MODULE.choose_desktop_session_env(
        [
            (
                2500,
                1000,
                {
                    "DISPLAY": ":99",
                    "XAUTHORITY": "/tmp/missing.auth",
                },
            ),
            (
                1200,
                1000,
                {
                    "DISPLAY": ":0",
                    "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.valid",
                    "WAYLAND_DISPLAY": "wayland-0",
                    "XDG_RUNTIME_DIR": "/run/user/1000",
                },
            ),
        ],
        uid=1000,
    )

    assert resolved == {
        "DISPLAY": ":0",
        "XAUTHORITY": "/run/user/1000/.mutter-Xwaylandauth.valid",
        "WAYLAND_DISPLAY": "wayland-0",
        "XDG_RUNTIME_DIR": "/run/user/1000",
    }


def test_choose_desktop_session_env_filters_out_other_users(monkeypatch) -> None:
    monkeypatch.setattr(MODULE.os.path, "exists", lambda path: True)
    monkeypatch.setattr(MODULE.os.path, "isdir", lambda path: True)

    resolved = MODULE.choose_desktop_session_env(
        [
            (2000, 1001, {"DISPLAY": ":0", "XAUTHORITY": "/tmp/auth"}),
            (2001, 1000, {"WAYLAND_DISPLAY": "wayland-0"}),
        ],
        uid=1000,
    )

    assert resolved is None
