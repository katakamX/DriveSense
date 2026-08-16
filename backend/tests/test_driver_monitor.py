"""The driver-monitor socket's own behaviour: accept, score, error, close.

`app.core.monitor` has its own detector-level tests (`test_monitor_detector.py`)
that fake the landmark extractor. This file is one layer up: it fakes
`MonitorSession` itself, because constructing a real one downloads a model
bundle and initialises MediaPipe — both wrong for a test that is about the
socket's protocol, not the detector's accuracy.

`decode_frame` is real throughout. It is cheap, has no external dependency,
and the malformed-frame test needs its actual `FrameDecodeError`.
"""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.v1 import driver_monitor as driver_monitor_route
from app.core.monitor import MonitorResult

DEFAULT_RESULT = MonitorResult(
    face_detected=True,
    not_visible=False,
    ear=0.30,
    mar=0.10,
    eyes_closed=False,
    drowsy=False,
    yawning=False,
)


def _valid_frame_data_url() -> str:
    """An 8x8 black JPEG, base64-encoded — enough for `decode_frame` to accept."""
    ok, buffer = cv2.imencode(".jpg", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(buffer.tobytes()).decode()


class FakeMonitorSession:
    """Stand-in for `MonitorSession`, installed via `monkeypatch` per test.

    `on_observe` is called once per frame; raising from it is how a test
    simulates `_score` failing. Instances are tracked on the class so a test
    can assert on the one the endpoint actually built and closed.
    """

    instances: list[FakeMonitorSession] = []

    def __init__(self, on_observe: Callable[[], MonitorResult] | None = None) -> None:
        self.closed = False
        self.observe_calls = 0
        self._on_observe = on_observe if on_observe is not None else lambda: DEFAULT_RESULT
        FakeMonitorSession.instances.append(self)

    def observe(self, frame_bgr: Any, now_s: float) -> MonitorResult:
        self.observe_calls += 1
        return self._on_observe()

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_fake_sessions() -> None:
    FakeMonitorSession.instances = []


def _install_session(
    monkeypatch: pytest.MonkeyPatch, on_observe: Callable[[], MonitorResult] | None = None
) -> None:
    monkeypatch.setattr(
        driver_monitor_route,
        "MonitorSession",
        lambda: FakeMonitorSession(on_observe),
    )


# --- happy path ---------------------------------------------------------------


def test_a_valid_frame_gets_back_a_reading(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_session(monkeypatch)

    with client.websocket_connect("/api/v1/ws/driver-monitor/DRV-1001") as socket:
        socket.send_json({"frame": _valid_frame_data_url()})
        message = socket.receive_json()

    assert message["type"] == "reading"
    assert message["driver_code"] == "DRV-1001"
    assert message["face_detected"] is True
    assert message["ear"] == pytest.approx(0.30)
    assert FakeMonitorSession.instances[0].observe_calls == 1


# --- driver code validation ----------------------------------------------------


def test_oversized_driver_code_closes_with_4400(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    too_long = "X" * 65
    with (
        pytest.raises(WebSocketDisconnect) as caught,
        client.websocket_connect(f"/api/v1/ws/driver-monitor/{too_long}") as socket,
    ):
        socket.receive_json()

    assert caught.value.code == 4400


# --- malformed / bad frames -----------------------------------------------------


def test_malformed_message_gets_an_error_and_the_socket_stays_open(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_session(monkeypatch)

    with client.websocket_connect("/api/v1/ws/driver-monitor/DRV-1001") as socket:
        socket.send_json({"not_frame": "oops"})
        error = socket.receive_json()
        assert error["type"] == "error"
        assert "frame" in error["detail"]

        # The socket is still usable after a malformed message.
        socket.send_json({"frame": _valid_frame_data_url()})
        reading = socket.receive_json()
        assert reading["type"] == "reading"


def test_undecodable_frame_gets_an_error_and_the_socket_stays_open(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_session(monkeypatch)

    with client.websocket_connect("/api/v1/ws/driver-monitor/DRV-1001") as socket:
        socket.send_json({"frame": "not-valid-base64!!"})
        error = socket.receive_json()

    assert error["type"] == "error"
    assert error["driver_code"] == "DRV-1001"


# --- scoring failure -------------------------------------------------------------


def test_an_unexpected_scoring_error_gets_a_generic_error_not_a_crash(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom() -> MonitorResult:
        raise RuntimeError("landmark extractor exploded")

    _install_session(monkeypatch, on_observe=_boom)

    with client.websocket_connect("/api/v1/ws/driver-monitor/DRV-1001") as socket:
        socket.send_json({"frame": _valid_frame_data_url()})
        error = socket.receive_json()
        assert error["type"] == "error"
        assert error["detail"] == "frame could not be scored"

        # One bad frame does not end the session.
        socket.send_json({"frame": _valid_frame_data_url()})
        second = socket.receive_json()
        assert second["type"] == "error"


# --- session construction failure -------------------------------------------------


def test_session_construction_failure_closes_with_1011(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from starlette.websockets import WebSocketDisconnect

    def _raise() -> FakeMonitorSession:
        raise RuntimeError("model bundle missing")

    monkeypatch.setattr(driver_monitor_route, "MonitorSession", _raise)

    with (
        pytest.raises(WebSocketDisconnect) as caught,
        client.websocket_connect("/api/v1/ws/driver-monitor/DRV-1001") as socket,
    ):
        socket.receive_json()

    assert caught.value.code == 1011


# --- lifecycle -------------------------------------------------------------------


def test_the_session_is_closed_when_the_client_disconnects(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_session(monkeypatch)

    with client.websocket_connect("/api/v1/ws/driver-monitor/DRV-1001") as socket:
        socket.send_json({"frame": _valid_frame_data_url()})
        socket.receive_json()
        socket.close(1000)

    assert FakeMonitorSession.instances[0].closed is True
