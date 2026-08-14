/**
 * Live WS client for a trip's telemetry + driving-event stream.
 *
 * Message envelope matches backend/app/schemas/live.py's LiveMessage:
 * { type: 'telemetry' | 'event', data: {...} }. Reconnect-on-drop is out of
 * scope here (deferred to Milestone 11) — a closed connection just reports
 * 'unreachable'.
 */
import { useEffect, useState } from 'react';

import type { ConnectionState } from '@/lib/api/useHealth';

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
 * The backend's LiveMessage.type is a four-way literal — `risk` (1 Hz, from
 * the inference tick) and `driver_state` (1 Hz, from the CV process) share
 * this socket with `telemetry` and `event`. This page renders neither, but
 * they must still be named here so the dispatch below can ignore them by
 * name rather than lumping every non-telemetry frame in with the events.
 */
interface LiveEnvelope {
  type: 'telemetry' | 'event' | 'risk' | 'driver_state';
  data: LiveTelemetry | LiveEvent | Record<string, unknown>;
}

const MAX_EVENTS = 20;

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

function buildWsUrl(tripId: string): string {
  const suffix = `/trips/${tripId}/live`;
  if (/^https?:\/\//.test(API_BASE)) {
    return `${API_BASE.replace(/^http/, 'ws')}${suffix}`;
  }
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${window.location.host}${API_BASE}${suffix}`;
}

export interface LiveTripState {
  state: ConnectionState;
  latestFrame: LiveTelemetry | null;
  events: LiveEvent[];
}

export function useLiveTrip(tripId: string): LiveTripState {
  const [state, setState] = useState<ConnectionState>('checking');
  const [latestFrame, setLatestFrame] = useState<LiveTelemetry | null>(null);
  const [events, setEvents] = useState<LiveEvent[]>([]);

  useEffect(() => {
    setState('checking');
    setLatestFrame(null);
    setEvents([]);

    const ws = new WebSocket(buildWsUrl(tripId));

    ws.onopen = () => setState('connected');
    ws.onclose = () => setState('unreachable');
    ws.onerror = () => setState('unreachable');
    ws.onmessage = (event: MessageEvent<string>) => {
      const message = JSON.parse(event.data) as LiveEnvelope;
      if (message.type === 'telemetry') {
        setLatestFrame(message.data as LiveTelemetry);
      } else if (message.type === 'event') {
        setEvents((prev) => [message.data as LiveEvent, ...prev].slice(0, MAX_EVENTS));
      }
      // `risk` and `driver_state` are dropped: nothing on this page consumes
      // them yet. Unknown future types fall through here too.
    };

    return () => {
      ws.close();
    };
  }, [tripId]);

  return { state, latestFrame, events };
}
