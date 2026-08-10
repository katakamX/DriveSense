"""In-process per-trip WebSocket fan-out.

No Redis, no cross-process state — single-worker topology makes this
sufficient (see docs/adr/0003-defer-redis.md). Queues are bounded; a slow
consumer drops its oldest buffered message rather than blocking publishers
or growing without bound (ADR 0001's latest-value-wins policy, minimal
version — full backpressure hardening is M11).
"""

import asyncio
import contextlib
import uuid
from typing import Any

_QUEUE_MAXSIZE = 100

_subscribers: dict[uuid.UUID, set[asyncio.Queue[dict[str, Any]]]] = {}


def subscribe(trip_id: uuid.UUID) -> asyncio.Queue[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    _subscribers.setdefault(trip_id, set()).add(queue)
    return queue


def unsubscribe(trip_id: uuid.UUID, queue: asyncio.Queue[dict[str, Any]]) -> None:
    queues = _subscribers.get(trip_id)
    if queues is None:
        return
    queues.discard(queue)
    if not queues:
        del _subscribers[trip_id]


def publish(trip_id: uuid.UUID, message: dict[str, Any]) -> None:
    for queue in _subscribers.get(trip_id, ()):
        if queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                queue.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(message)


def subscriber_count(trip_id: uuid.UUID) -> int:
    return len(_subscribers.get(trip_id, ()))
