/**
 * Live WS client for a trip's telemetry, risk and driving-event stream.
 *
 * Message envelope matches `backend/app/schemas/live.py`'s `LiveMessage`:
 * `{ type, data }`.
 *
 * ## Reconnect
 *
 * Capped exponential backoff with full jitter (`./backoff`), the same policy
 * `useDriverMonitor` runs. The failure this exists for is the backend
 * restarting, which every open tab notices at the same instant — a fixed ladder
 * would have them all retry in lockstep and hit the recovering server as one
 * wave. Close code 4404 is terminal: the trip does not exist, and it will go on
 * not existing. A clean 1000 from our own teardown is not retried either.
 *
 * ## What survives a reconnect, and why it is the client's job
 *
 * State is cleared when `tripId` changes and at no other time. A dropped socket
 * does not blank the page: the last speed, the last risk band and the event
 * list stay on screen, labelled `reconnecting`, because they are still the most
 * recent thing known about the drive and replacing them with dashes would be
 * less true, not more.
 *
 * This is what makes the backend's restart survivable. The server comes back
 * with an empty ring buffer and no last inference, so its snapshot is thin —
 * see `app/core/live/snapshot.py`, which deliberately does not fake continuity
 * it does not have. Continuity lives here instead, in a client that kept what
 * it was already showing.
 *
 * ## Silence is not the same as connected
 *
 * The server pings every ~20 s. A half-open connection — a sleeping laptop, a
 * proxy that dropped an idle tunnel — looks exactly like a quiet trip to the
 * browser, and `readyState` will happily report OPEN for minutes. So a socket
 * that has said nothing for `SILENCE_LIMIT_MS` is treated as dead and closed,
 * which puts it back through the ordinary retry path.
 */
import { useEffect, useRef, useState } from 'react';

import { STABLE_CONNECTION_MS, nextDelayMs } from '@/lib/ws/backoff';
import { buildWsUrl } from '@/lib/ws/url';

export type LiveConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'unreachable';

export interface LiveTelemetry {
  recorded_at: string;
  speed_kph: number;
  accel_ms2: number;
  lateral_accel_ms2: number;
  lat: number | null;
  lon: number | null;
}

export interface LiveEvent {
  event_type: string;
  occurred_at: string;
  measured_value: number;
  threshold_value: number;
}

/**
 * One window's assessment, mirroring `RiskOut` in `backend/app/schemas/risk.py`.
 *
 * Named fields stop at what a live view can act on. The explanation the backend
 * also sends — contributions, probabilities, the model's own band — belongs to
 * the trip detail page, and naming it here would imply this hook keeps it.
 */
export interface LiveRisk {
  window_start: string;
  window_end: string;
  sample_count: number;
  coverage_ratio: number;
  score: number;
  band: 'CALM' | 'NORMAL' | 'AGGRESSIVE' | 'HIGH_RISK';
  confidence: number;
  provenance: 'RULES_ONLY' | 'MODEL_AND_RULES_AGREE' | 'MODEL_ONLY';
  model_available: boolean;
  gated: boolean;
  matched_rules: string[];
}

interface LiveSnapshot {
  telemetry: LiveTelemetry | null;
  risk: LiveRisk | null;
  events: LiveEvent[];
}

interface LiveEnvelope {
  type: 'telemetry' | 'event' | 'risk' | 'driver_state' | 'snapshot' | 'ping';
  data: unknown;
}

const MAX_EVENTS = 20;

/** After this long failing, stop calling it 'reconnecting' and admit it's down. */
const UNREACHABLE_AFTER_MS = 30_000;

/**
 * Silence that means the connection is gone rather than the trip is quiet.
 * Comfortably more than two server ping intervals, so one dropped heartbeat
 * does not cost a working connection.
 */
const SILENCE_LIMIT_MS = 45_000;
const SILENCE_CHECK_MS = 5_000;

/** 1000: our own teardown. 4404: the trip does not exist, and retrying cannot help. */
const TERMINAL_CLOSE_CODES = new Set([1000, 4404]);

export interface LiveTripState {
  state: LiveConnectionState;
  latestFrame: LiveTelemetry | null;
  latestRisk: LiveRisk | null;
  events: LiveEvent[];
}

export function useLiveTrip(tripId: string): LiveTripState {
  const [state, setState] = useState<LiveConnectionState>('connecting');
  const [latestFrame, setLatestFrame] = useState<LiveTelemetry | null>(null);
  const [latestRisk, setLatestRisk] = useState<LiveRisk | null>(null);
  const [events, setEvents] = useState<LiveEvent[]>([]);

  const lastMessageAtRef = useRef(0);

  useEffect(() => {
    // The only place any of this is discarded: a different trip is a different
    // drive, and none of the previous one's numbers describe it.
    setState('connecting');
    setLatestFrame(null);
    setLatestRisk(null);
    setEvents([]);

    if (!tripId) {
      return;
    }

    let disposed = false;
    let socket: WebSocket | null = null;
    let attempt = 0;
    let openedAt = 0;
    let firstFailureAt: number | null = null;
    let retryTimer: number | undefined;

    const applySnapshot = (snapshot: LiveSnapshot): void => {
      // Every field is applied only when the server actually has it. After a
      // restart the first two are null and the client keeps what it was
      // already showing.
      if (snapshot.telemetry) {
        setLatestFrame(snapshot.telemetry);
      }
      if (snapshot.risk) {
        setLatestRisk(snapshot.risk);
      }
      if (snapshot.events?.length) {
        // Replaced rather than merged: driving events are written before they
        // are published, so this list is the table's own answer and already
        // contains everything the client had. Merging would duplicate exactly
        // the rows a reconnecting client is most likely to hold.
        setEvents(snapshot.events.slice(0, MAX_EVENTS));
      }
    };

    const scheduleRetry = (): void => {
      firstFailureAt ??= Date.now();
      const downFor = Date.now() - firstFailureAt;
      setState(downFor >= UNREACHABLE_AFTER_MS ? 'unreachable' : 'reconnecting');

      const delay = nextDelayMs(attempt);
      attempt += 1;
      retryTimer = window.setTimeout(connect, delay);
    };

    function connect(): void {
      if (disposed) {
        return;
      }
      const current = new WebSocket(buildWsUrl(`/trips/${encodeURIComponent(tripId)}/live`));
      socket = current;

      current.onopen = () => {
        openedAt = Date.now();
        firstFailureAt = null;
        lastMessageAtRef.current = Date.now();
        setState('connected');
      };

      current.onmessage = (event: MessageEvent<string>) => {
        lastMessageAtRef.current = Date.now();
        let message: LiveEnvelope;
        try {
          message = JSON.parse(event.data) as LiveEnvelope;
        } catch {
          return;
        }
        switch (message.type) {
          case 'snapshot':
            applySnapshot(message.data as LiveSnapshot);
            break;
          case 'telemetry':
            setLatestFrame(message.data as LiveTelemetry);
            break;
          case 'risk':
            setLatestRisk(message.data as LiveRisk);
            break;
          case 'event':
            setEvents((prev) => [message.data as LiveEvent, ...prev].slice(0, MAX_EVENTS));
            break;
          // `ping` has already done its job by arriving, and `driver_state`
          // belongs to a page that is not this one. Unknown future types land
          // here too, which is what keeps an older client working against a
          // newer server.
          default:
            break;
        }
      };

      current.onerror = () => {
        // Always followed by onclose, which is where the retry is decided.
        // Handling both would schedule two retries for one failure.
      };

      current.onclose = (event: CloseEvent) => {
        socket = null;
        if (disposed) {
          return;
        }
        if (TERMINAL_CLOSE_CODES.has(event.code)) {
          setState('unreachable');
          return;
        }
        // Only a connection that actually held counts as a success worth
        // resetting the backoff for — otherwise a server that accepts and
        // immediately drops turns the retry loop into a hot one.
        if (openedAt > 0 && Date.now() - openedAt >= STABLE_CONNECTION_MS) {
          attempt = 0;
        }
        scheduleRetry();
      };
    }

    const silenceTimer = window.setInterval(() => {
      if (socket?.readyState !== WebSocket.OPEN) {
        return;
      }
      if (Date.now() - lastMessageAtRef.current >= SILENCE_LIMIT_MS) {
        // Not code 1000: this is a failure, and `onclose` has to retry it
        // rather than read it as our own teardown.
        socket.close(4000, 'no traffic');
      }
    }, SILENCE_CHECK_MS);

    connect();

    return () => {
      disposed = true;
      window.clearTimeout(retryTimer);
      window.clearInterval(silenceTimer);
      socket?.close(1000, 'client navigating away');
      socket = null;
    };
  }, [tripId]);

  return { state, latestFrame, latestRisk, events };
}
