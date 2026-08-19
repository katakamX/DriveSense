"""`LiveTripListener` — message handling and the stop-event lifecycle.

No real socket is opened. `_handle` is exercised directly for message-type
logic; `run()` is exercised against fake `websockets.connect` stand-ins that
behave like a live socket (they block on `__anext__` once exhausted, the way
an idle real connection would) so the stop-event cancellation path is real.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
import websockets

from drivesense_bench.ws_listener import LiveTripListener


class ScriptedFakeSocket:
    """Yields the given messages, then idles like an open, quiet socket."""

    def __init__(self, messages: list[str]) -> None:
        self._messages = list(messages)

    def __aiter__(self) -> AsyncIterator[str]:
        return self

    async def __anext__(self) -> str:
        if self._messages:
            return self._messages.pop(0)
        await asyncio.sleep(10)
        raise AssertionError("idle socket should have been cancelled, not exhausted")

    async def __aenter__(self) -> ScriptedFakeSocket:
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False


def test_telemetry_message_is_recorded_by_seq() -> None:
    listener = LiveTripListener()
    listener._handle(json.dumps({"type": "telemetry", "data": {"seq": 7}}))
    assert set(listener.received_at) == {7}


def test_telemetry_message_without_seq_records_nothing() -> None:
    listener = LiveTripListener()
    listener._handle(json.dumps({"type": "telemetry", "data": {}}))
    assert listener.received_at == {}


@pytest.mark.parametrize(
    ("msg_type", "counter"),
    [
        ("risk", "risk_messages"),
        ("event", "event_messages"),
        ("snapshot", "snapshot_messages"),
        ("ping", "ping_messages"),
    ],
)
def test_non_telemetry_types_are_counted(msg_type: str, counter: str) -> None:
    listener = LiveTripListener()
    listener._handle(json.dumps({"type": msg_type, "data": {}}))
    assert getattr(listener, counter) == 1


def test_unrecognized_type_is_counted() -> None:
    listener = LiveTripListener()
    listener._handle(json.dumps({"type": "something_new", "data": {}}))
    assert listener.unrecognized == 1


def test_non_json_message_is_counted_and_does_not_raise() -> None:
    listener = LiveTripListener()
    listener._handle(b"\xff\xfe not json")
    assert listener.unrecognized == 1


async def test_run_processes_messages_then_stops_on_the_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages = [json.dumps({"type": "telemetry", "data": {"seq": 42}})]
    monkeypatch.setattr(websockets, "connect", lambda url: ScriptedFakeSocket(messages))

    listener = LiveTripListener()
    stop = asyncio.Event()

    async def trigger_stop() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.wait_for(
        asyncio.gather(listener.run("ws://fake", stop), trigger_stop()), timeout=5
    )

    assert 42 in listener.received_at


async def test_run_records_a_connect_failure_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(url: str) -> None:
        raise TimeoutError("timed out during opening handshake")

    monkeypatch.setattr(websockets, "connect", refuse)

    listener = LiveTripListener()
    stop = asyncio.Event()

    await asyncio.wait_for(listener.run("ws://fake", stop), timeout=5)

    assert listener.connect_error is not None
    assert listener.received_at == {}
