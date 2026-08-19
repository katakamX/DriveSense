import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import {
  fetchRiskWindows,
  fetchTripEvents,
  fetchTripTelemetry,
  type RiskWindow,
  type TelemetryPoint,
  type TripEvent,
} from '@/lib/api/tripDetail';

const BAND_TONE: Record<string, BadgeTone> = {
  CALM: 'low',
  NORMAL: 'neutral',
  AGGRESSIVE: 'high',
  HIGH_RISK: 'critical',
};

const EVENT_TONE: Record<string, BadgeTone> = {
  harsh_braking: 'high',
  rapid_acceleration: 'high',
  speeding: 'critical',
};

function RiskWindowsPanel({ windows }: { windows: RiskWindow[] }) {
  return (
    <Panel className="overflow-hidden p-0">
      <div className="border-b border-border-subtle px-5 py-3 text-sm font-medium text-content-secondary">
        Risk breakdown
      </div>
      {windows.length === 0 ? (
        <p className="p-5 text-content-muted">No risk windows for this trip yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-subtle text-left text-content-muted">
              <th className="px-5 py-3 font-medium">Window</th>
              <th className="px-5 py-3 font-medium">Band</th>
              <th className="px-5 py-3 font-medium">Score</th>
              <th className="px-5 py-3 font-medium">Coverage</th>
              <th className="px-5 py-3 font-medium">Matched rules</th>
            </tr>
          </thead>
          <tbody>
            {windows.map((window) => (
              <tr key={window.id} className="border-b border-border-subtle last:border-0">
                <td className="tabular px-5 py-3 text-content-secondary">
                  {new Date(window.window_start).toLocaleTimeString()} –{' '}
                  {new Date(window.window_end).toLocaleTimeString()}
                </td>
                <td className="px-5 py-3">
                  <Badge tone={BAND_TONE[window.band] ?? 'neutral'}>{window.band}</Badge>
                </td>
                <td className="tabular px-5 py-3 text-content-primary">
                  {window.score.toFixed(1)}
                </td>
                <td className="tabular px-5 py-3 text-content-secondary">
                  {(window.coverage_ratio * 100).toFixed(0)}%
                </td>
                <td className="px-5 py-3 text-content-secondary">
                  {window.matched_rules.length > 0 ? window.matched_rules.join(', ') : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

function EventsPanel({ events }: { events: TripEvent[] }) {
  return (
    <Panel className="overflow-hidden p-0">
      <div className="border-b border-border-subtle px-5 py-3 text-sm font-medium text-content-secondary">
        Events
      </div>
      {events.length === 0 ? (
        <p className="p-5 text-content-muted">No events recorded for this trip.</p>
      ) : (
        <ul>
          {events.map((event) => (
            <li
              key={event.id}
              className="flex items-center justify-between border-b border-border-subtle px-5 py-3 last:border-0"
            >
              <Badge tone={EVENT_TONE[event.event_type] ?? 'neutral'}>{event.event_type}</Badge>
              <span className="tabular text-sm text-content-secondary">
                {event.measured_value.toFixed(2)} / {event.threshold_value.toFixed(2)}
              </span>
              <span className="tabular text-xs text-content-muted">
                {new Date(event.occurred_at).toLocaleTimeString()}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function RoutePanel({ points }: { points: TelemetryPoint[] }) {
  const withLocation = points.filter((point) => point.lat != null && point.lon != null);
  return (
    <Panel className="overflow-hidden p-0">
      <div className="border-b border-border-subtle px-5 py-3 text-sm font-medium text-content-secondary">
        Route ({withLocation.length} points)
      </div>
      {withLocation.length === 0 ? (
        <p className="p-5 text-content-muted">No route data for this trip.</p>
      ) : (
        <div className="max-h-80 overflow-y-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-left text-content-muted">
                <th className="px-5 py-3 font-medium">Time</th>
                <th className="px-5 py-3 font-medium">Speed</th>
                <th className="px-5 py-3 font-medium">GPS</th>
              </tr>
            </thead>
            <tbody>
              {withLocation.map((point) => (
                <tr key={point.id} className="border-b border-border-subtle last:border-0">
                  <td className="tabular px-5 py-3 text-content-secondary">
                    {new Date(point.recorded_at).toLocaleTimeString()}
                  </td>
                  <td className="tabular px-5 py-3 text-content-primary">
                    {point.speed_kph.toFixed(1)} km/h
                  </td>
                  <td className="tabular px-5 py-3 text-content-secondary">
                    {point.lat?.toFixed(4)}, {point.lon?.toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

export function TripDetail() {
  const { tripId } = useParams<{ tripId: string }>();
  const [windows, setWindows] = useState<RiskWindow[] | null>(null);
  const [events, setEvents] = useState<TripEvent[]>([]);
  const [telemetry, setTelemetry] = useState<TelemetryPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tripId) return;
    const controller = new AbortController();
    setWindows(null);
    setError(null);

    const load = async (): Promise<void> => {
      try {
        const [windowList, eventList, telemetryList] = await Promise.all([
          fetchRiskWindows(tripId, controller.signal),
          fetchTripEvents(tripId, controller.signal),
          fetchTripTelemetry(tripId, controller.signal),
        ]);
        setWindows(windowList);
        setEvents(eventList);
        setTelemetry(telemetryList);
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Could not load trip detail');
        }
      }
    };

    void load();
    return () => controller.abort();
  }, [tripId]);

  return (
    <div>
      <h1 className="text-2xl font-semibold">Trip detail</h1>
      <p className="mt-1 text-content-secondary">Trip {tripId}</p>

      {error && <p className="mt-6 text-risk-critical">{error}</p>}
      {!error && windows === null && <p className="mt-6 text-content-muted">Loading…</p>}
      {!error && windows !== null && (
        <div className="mt-6 flex flex-col gap-6">
          <RiskWindowsPanel windows={windows} />
          <EventsPanel events={events} />
          <RoutePanel points={telemetry} />
        </div>
      )}
    </div>
  );
}
