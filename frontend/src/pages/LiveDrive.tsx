import { useParams } from 'react-router-dom';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { StatTile } from '@/components/ui/StatTile';
import type { ConnectionState } from '@/lib/api/useHealth';
import { useLiveTrip } from '@/lib/ws/useLiveTrip';

const CONNECTION_LABEL: Record<ConnectionState, { text: string; dot: string }> = {
  checking: { text: 'Connecting', dot: 'bg-content-muted' },
  connected: { text: 'Live', dot: 'bg-risk-low' },
  unreachable: { text: 'Disconnected', dot: 'bg-risk-critical' },
};

/**
 * Event rows come straight off the socket, so a malformed or partial payload
 * must degrade to a dash rather than take the whole page down with it.
 */
function formatMeasure(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '—';
}

const EVENT_TONE: Record<string, BadgeTone> = {
  harsh_braking: 'high',
  rapid_acceleration: 'high',
  speeding: 'critical',
};

export function LiveDrive() {
  const { tripId } = useParams<{ tripId: string }>();
  const { state, latestFrame, events } = useLiveTrip(tripId ?? '');
  const label = CONNECTION_LABEL[state];

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Live Drive</h1>
          <p className="mt-1 text-content-secondary">Trip {tripId}</p>
        </div>
        <div className="flex items-center gap-2.5 rounded-lg border border-border-subtle bg-surface-raised px-3 py-1.5">
          <span className={`h-2 w-2 rounded-full ${label.dot}`} aria-hidden="true" />
          <span className="text-sm text-content-primary">{label.text}</span>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatTile
          label="Speed"
          value={latestFrame ? latestFrame.speed_kph.toFixed(1) : '—'}
          unit="km/h"
        />
        <StatTile
          label="Accel"
          value={latestFrame ? latestFrame.accel_ms2.toFixed(2) : '—'}
          unit="m/s²"
        />
        <StatTile
          label="Lateral accel"
          value={latestFrame ? latestFrame.lateral_accel_ms2.toFixed(2) : '—'}
          unit="m/s²"
        />
        <StatTile
          label="GPS"
          value={
            latestFrame?.lat != null && latestFrame.lon != null
              ? `${latestFrame.lat.toFixed(4)}, ${latestFrame.lon.toFixed(4)}`
              : '—'
          }
        />
      </div>

      <Panel className="mt-6 overflow-hidden p-0">
        <div className="border-b border-border-subtle px-5 py-3 text-sm font-medium text-content-secondary">
          Recent events
        </div>
        {events.length === 0 ? (
          <p className="p-5 text-content-muted">No events yet.</p>
        ) : (
          <ul>
            {events.map((event, index) => (
              <li
                key={`${event.occurred_at}-${index}`}
                className="flex items-center justify-between border-b border-border-subtle px-5 py-3 last:border-0"
              >
                <Badge tone={EVENT_TONE[event.event_type] ?? 'neutral'}>{event.event_type}</Badge>
                <span className="tabular text-sm text-content-secondary">
                  {formatMeasure(event.measured_value)} / {formatMeasure(event.threshold_value)}
                </span>
                <span className="tabular text-xs text-content-muted">
                  {new Date(event.occurred_at).toLocaleTimeString()}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
