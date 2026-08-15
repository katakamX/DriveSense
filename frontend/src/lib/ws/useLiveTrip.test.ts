/**
 * The reconnect behaviour M11 exists for, driven against a fake socket.
 *
 * The interesting assertions are all about *time* — how long before the next
 * attempt, how long before the page stops claiming to be live — so the clock is
 * faked and advanced deliberately. `Math.random` is pinned too: the backoff
 * uses full jitter, and a delay drawn from a real random source would make
 * every timing assertion a coin flip.
 */
import { renderHook, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_BASE_MS, DEFAULT_CAP_MS } from '@/lib/ws/backoff';
import { useLiveTrip } from '@/lib/ws/useLiveTrip';

interface CloseInit {
  code?: number;
}

class FakeSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  /** Every socket the hook has constructed, in order. */
  static instances: FakeSocket[] = [];

  readyState = FakeSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onclose: ((event: CloseInit) => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  closedWith: number | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  /** Called by the hook's teardown and by its silence watchdog. */
  close(code?: number): void {
    if (this.readyState === FakeSocket.CLOSED) {
      return;
    }
    this.readyState = FakeSocket.CLOSED;
    this.closedWith = code ?? 1000;
    this.onclose?.({ code: code ?? 1000 });
  }

  // --- test-side controls ---

  accept(): void {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }

  /** A drop initiated by the server or the network, not by us. */
  drop(code = 1006): void {
    this.readyState = FakeSocket.CLOSED;
    this.onclose?.({ code });
  }

  deliver(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) });
  }
}

const TELEMETRY = {
  recorded_at: '2026-08-11T09:00:01Z',
  speed_kph: 52.5,
  accel_ms2: 0.8,
  lateral_accel_ms2: 0.2,
  lat: null,
  lon: null,
};

const EVENT = {
  event_type: 'harsh_braking',
  occurred_at: '2026-08-11T09:00:02Z',
  measured_value: -5.5,
  threshold_value: -3.5,
};

const RISK = {
  window_start: '2026-08-11T09:00:00Z',
  window_end: '2026-08-11T09:00:30Z',
  sample_count: 300,
  coverage_ratio: 1.0,
  score: 71.5,
  band: 'AGGRESSIVE',
  confidence: 0.8,
  provenance: 'MODEL_AND_RULES_AGREE',
  model_available: true,
  gated: false,
  matched_rules: ['harsh_braking'],
};

function snapshot(data: Partial<Record<'telemetry' | 'risk' | 'events', unknown>>) {
  return {
    type: 'snapshot',
    data: { telemetry: null, risk: null, events: [], ...data },
  };
}

function latest(): FakeSocket {
  const socket = FakeSocket.instances.at(-1);
  if (!socket) {
    throw new Error('the hook has not opened a socket');
  }
  return socket;
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeSocket);
  vi.useFakeTimers();
  // Full jitter draws the whole interval from `random()`; pinning it at 1
  // makes each delay exactly its (capped) ceiling, which is the only value a
  // test can assert on without re-implementing the policy.
  vi.spyOn(Math, 'random').mockReturnValue(1);
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('connecting', () => {
  it('opens a socket for the trip and reports connected once it holds', () => {
    const { result } = renderHook(() => useLiveTrip('trip-1'));
    expect(result.current.state).toBe('connecting');
    expect(latest().url).toContain('/trips/trip-1/live');

    act(() => latest().accept());
    expect(result.current.state).toBe('connected');
  });

  it('applies the connect-time snapshot', () => {
    const { result } = renderHook(() => useLiveTrip('trip-1'));
    act(() => {
      latest().accept();
      latest().deliver(snapshot({ telemetry: TELEMETRY, risk: RISK, events: [EVENT] }));
    });

    expect(result.current.latestFrame?.speed_kph).toBe(52.5);
    expect(result.current.latestRisk?.band).toBe('AGGRESSIVE');
    expect(result.current.events).toHaveLength(1);
  });

  it('surfaces risk frames, which the page used to drop on the floor', () => {
    const { result } = renderHook(() => useLiveTrip('trip-1'));
    act(() => {
      latest().accept();
      latest().deliver({ type: 'risk', data: RISK });
    });

    expect(result.current.latestRisk?.score).toBe(71.5);
  });

  it('ignores message types it has no use for rather than mistaking them for events', () => {
    const { result } = renderHook(() => useLiveTrip('trip-1'));
    act(() => {
      latest().accept();
      latest().deliver({ type: 'driver_state', data: { drowsiness: 0.9 } });
      latest().deliver({ type: 'ping', data: { sent_at: '2026-08-11T09:00:20Z' } });
      latest().deliver({ type: 'something_added_in_m14', data: {} });
    });

    expect(result.current.events).toEqual([]);
    expect(result.current.state).toBe('connected');
  });
});

describe('retry scheduling', () => {
  it('waits out the backoff before the next attempt', () => {
    renderHook(() => useLiveTrip('trip-1'));
    act(() => latest().accept());
    act(() => latest().drop());

    expect(FakeSocket.instances).toHaveLength(1);
    act(() => void vi.advanceTimersByTime(DEFAULT_BASE_MS - 1));
    expect(FakeSocket.instances).toHaveLength(1);

    act(() => void vi.advanceTimersByTime(1));
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it('backs off further with each failure, and stops at the cap', () => {
    renderHook(() => useLiveTrip('trip-1'));

    const delays: number[] = [];
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const before = FakeSocket.instances.length;
      act(() => latest().drop());
      // Never opened, so the attempt counter is not reset: each drop is one
      // more step up the ladder.
      const expected = Math.min(DEFAULT_CAP_MS, DEFAULT_BASE_MS * 2 ** attempt);
      act(() => void vi.advanceTimersByTime(expected));
      expect(FakeSocket.instances.length).toBe(before + 1);
      delays.push(expected);
    }

    expect(delays[0]).toBe(DEFAULT_BASE_MS);
    expect(delays.at(-1)).toBe(DEFAULT_CAP_MS);
  });

  it('resets the ladder only for a connection that actually held', () => {
    renderHook(() => useLiveTrip('trip-1'));

    // Two failures without ever opening: the third wait is 2 × base.
    act(() => latest().drop());
    act(() => void vi.advanceTimersByTime(DEFAULT_BASE_MS));
    act(() => latest().drop());
    act(() => void vi.advanceTimersByTime(DEFAULT_BASE_MS * 2));
    const afterFailures = FakeSocket.instances.length;

    // Now one that holds for longer than STABLE_CONNECTION_MS.
    act(() => latest().accept());
    act(() => void vi.advanceTimersByTime(10_000));
    act(() => latest().drop());

    act(() => void vi.advanceTimersByTime(DEFAULT_BASE_MS));
    expect(FakeSocket.instances.length).toBe(afterFailures + 1);
  });

  it('admits it is down once the retries have been failing long enough', () => {
    const { result } = renderHook(() => useLiveTrip('trip-1'));
    act(() => latest().accept());
    act(() => latest().drop());
    expect(result.current.state).toBe('reconnecting');

    for (let attempt = 0; attempt < 8; attempt += 1) {
      act(() => void vi.advanceTimersByTime(DEFAULT_CAP_MS));
      act(() => latest().drop());
    }

    expect(result.current.state).toBe('unreachable');
  });
});

describe('terminal closes', () => {
  it('does not retry 4404, because the trip will not start existing', () => {
    const { result } = renderHook(() => useLiveTrip('trip-1'));
    act(() => latest().drop(4404));

    expect(result.current.state).toBe('unreachable');
    act(() => void vi.advanceTimersByTime(DEFAULT_CAP_MS * 4));
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it('does not retry our own teardown', () => {
    const { unmount } = renderHook(() => useLiveTrip('trip-1'));
    act(() => latest().accept());
    unmount();

    expect(latest().closedWith).toBe(1000);
    act(() => void vi.advanceTimersByTime(DEFAULT_CAP_MS * 4));
    expect(FakeSocket.instances).toHaveLength(1);
  });
});

describe('what survives the drop', () => {
  it('keeps the last values on screen while reconnecting', () => {
    const { result } = renderHook(() => useLiveTrip('trip-1'));
    act(() => {
      latest().accept();
      latest().deliver({ type: 'telemetry', data: TELEMETRY });
      latest().deliver({ type: 'risk', data: RISK });
      latest().deliver({ type: 'event', data: EVENT });
    });

    act(() => latest().drop());

    expect(result.current.state).toBe('reconnecting');
    expect(result.current.latestFrame?.speed_kph).toBe(52.5);
    expect(result.current.latestRisk?.score).toBe(71.5);
    expect(result.current.events).toHaveLength(1);
  });

  it('survives a restarted backend, whose snapshot has nothing in it', () => {
    // The whole milestone in one test: the server comes back with an empty
    // ring buffer and no last inference, and the page must not blank.
    const { result } = renderHook(() => useLiveTrip('trip-1'));
    act(() => {
      latest().accept();
      latest().deliver({ type: 'telemetry', data: TELEMETRY });
      latest().deliver({ type: 'event', data: EVENT });
    });

    act(() => latest().drop());
    act(() => void vi.advanceTimersByTime(DEFAULT_BASE_MS));
    act(() => {
      latest().accept();
      latest().deliver(snapshot({}));
    });

    expect(result.current.state).toBe('connected');
    expect(result.current.latestFrame?.speed_kph).toBe(52.5);
    expect(result.current.events).toHaveLength(1);
  });

  it('takes the replayed event list over its own, without duplicating it', () => {
    const { result } = renderHook(() => useLiveTrip('trip-1'));
    act(() => {
      latest().accept();
      latest().deliver({ type: 'event', data: EVENT });
    });

    act(() => latest().drop());
    act(() => void vi.advanceTimersByTime(DEFAULT_BASE_MS));
    act(() => {
      latest().accept();
      // The table's answer: the event the client already had, plus one it
      // missed while the socket was down.
      latest().deliver(snapshot({ events: [{ ...EVENT, event_type: 'speeding' }, EVENT] }));
    });

    expect(result.current.events).toHaveLength(2);
    expect(result.current.events[0]?.event_type).toBe('speeding');
  });

  it('clears everything when the trip changes, and only then', () => {
    const { result, rerender } = renderHook(({ id }) => useLiveTrip(id), {
      initialProps: { id: 'trip-1' },
    });
    act(() => {
      latest().accept();
      latest().deliver({ type: 'telemetry', data: TELEMETRY });
      latest().deliver({ type: 'event', data: EVENT });
    });

    rerender({ id: 'trip-2' });

    expect(result.current.latestFrame).toBeNull();
    expect(result.current.latestRisk).toBeNull();
    expect(result.current.events).toEqual([]);
    expect(latest().url).toContain('/trips/trip-2/live');
  });
});

describe('silence', () => {
  it('drops a socket that has gone quiet, and retries it', () => {
    const { result } = renderHook(() => useLiveTrip('trip-1'));
    act(() => latest().accept());
    const stalled = latest();

    // Well past two server ping intervals with nothing arriving.
    act(() => void vi.advanceTimersByTime(50_000));

    expect(stalled.readyState).toBe(FakeSocket.CLOSED);
    expect(result.current.state).not.toBe('connected');
  });

  it('leaves a socket alone as long as it keeps speaking', () => {
    renderHook(() => useLiveTrip('trip-1'));
    act(() => latest().accept());
    const held = latest();

    for (let tick = 0; tick < 5; tick += 1) {
      act(() => void vi.advanceTimersByTime(20_000));
      act(() => held.deliver({ type: 'ping', data: { sent_at: '2026-08-11T09:00:20Z' } }));
    }

    expect(held.readyState).toBe(FakeSocket.OPEN);
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
