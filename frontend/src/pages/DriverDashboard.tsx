import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { getMyApplication, type DriverApplicationRead } from '@/lib/api/driverApplication';
import { fetchMyTrips, type MyTrip } from '@/lib/api/driverDashboard';

const APPLICATION_STATUS_TONE: Record<DriverApplicationRead['status'], BadgeTone> = {
  draft: 'neutral',
  pending: 'moderate',
  verified: 'low',
  rejected: 'critical',
};

const APPLICATION_STATUS_LABEL: Record<DriverApplicationRead['status'], string> = {
  draft: 'Draft',
  pending: 'Pending review',
  verified: 'Verified',
  rejected: 'Rejected',
};

const TRIP_STATUS_TONE: Record<string, BadgeTone> = {
  in_progress: 'moderate',
  completed: 'low',
};

const RISK_BAND_TONE: Record<string, BadgeTone> = {
  CALM: 'low',
  NORMAL: 'neutral',
  AGGRESSIVE: 'high',
  HIGH_RISK: 'critical',
};

const RISK_BAND_LABEL: Record<string, string> = {
  CALM: 'Calm',
  NORMAL: 'Normal',
  AGGRESSIVE: 'Aggressive',
  HIGH_RISK: 'High risk',
};

function ApplicationStatusPanel({ application }: { application: DriverApplicationRead | null }) {
  if (application === null) {
    return (
      <Panel className="p-6">
        <h2 className="text-sm font-medium text-content-secondary">Application status</h2>
        <p className="mt-2 text-content-primary">You haven&apos;t applied to drive yet.</p>
        <Link to="/become-a-driver" className="mt-3 inline-block text-accent hover:underline">
          Start an application →
        </Link>
      </Panel>
    );
  }

  return (
    <Panel className="p-6">
      <h2 className="text-sm font-medium text-content-secondary">Application status</h2>
      <div className="mt-2">
        <Badge tone={APPLICATION_STATUS_TONE[application.status]}>
          {APPLICATION_STATUS_LABEL[application.status]}
        </Badge>
      </div>
      {application.status !== 'verified' && (
        <Link to="/become-a-driver" className="mt-3 inline-block text-accent hover:underline">
          View application →
        </Link>
      )}
    </Panel>
  );
}

/** The most recent trip that actually has a risk assessment, if any. */
function latestScoredTrip(trips: MyTrip[]): MyTrip | null {
  return trips.find((trip) => trip.risk_band !== null) ?? null;
}

function MyRiskPanel({ trips }: { trips: MyTrip[] }) {
  const latest = latestScoredTrip(trips);

  return (
    <Panel className="p-6">
      <h2 className="text-sm font-medium text-content-secondary">My risk</h2>
      {latest === null || latest.risk_band === null ? (
        <p className="mt-2 text-content-muted">No risk data yet.</p>
      ) : (
        <>
          <div className="mt-2">
            <Badge tone={RISK_BAND_TONE[latest.risk_band] ?? 'neutral'}>
              {RISK_BAND_LABEL[latest.risk_band] ?? latest.risk_band}
            </Badge>
          </div>
          <p className="mt-2 text-content-muted">
            {latest.risk_score !== null ? `Score ${latest.risk_score.toFixed(1)}` : null} · from
            most recent trip
          </p>
        </>
      )}
    </Panel>
  );
}

function MyTripsPanel({ trips }: { trips: MyTrip[] }) {
  return (
    <Panel className="mt-6 overflow-hidden p-0">
      {trips.length === 0 ? (
        <p className="p-5 text-content-muted">No trips yet.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-subtle text-left text-content-muted">
              <th className="px-5 py-3 font-medium">Started</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium">Risk</th>
              <th className="px-5 py-3 font-medium" aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {trips.map((trip) => (
              <tr key={trip.id} className="border-b border-border-subtle last:border-0">
                <td className="tabular px-5 py-3 text-content-secondary">
                  {new Date(trip.started_at).toLocaleString()}
                </td>
                <td className="px-5 py-3">
                  <Badge tone={TRIP_STATUS_TONE[trip.status] ?? 'neutral'}>{trip.status}</Badge>
                </td>
                <td className="px-5 py-3">
                  {trip.risk_band === null ? (
                    <span className="text-content-muted">—</span>
                  ) : (
                    <Badge tone={RISK_BAND_TONE[trip.risk_band] ?? 'neutral'}>
                      {RISK_BAND_LABEL[trip.risk_band] ?? trip.risk_band}
                    </Badge>
                  )}
                </td>
                <td className="px-5 py-3 text-right">
                  <Link to={`/trips/${trip.id}/live`} className="text-accent hover:underline">
                    Live Drive →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Panel>
  );
}

export function DriverDashboard() {
  const [application, setApplication] = useState<DriverApplicationRead | null>(null);
  const [trips, setTrips] = useState<MyTrip[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    const load = async (): Promise<void> => {
      try {
        const [myApplication, myTrips] = await Promise.all([
          getMyApplication(),
          fetchMyTrips(controller.signal),
        ]);
        setApplication(myApplication);
        setTrips(myTrips);
      } catch {
        if (!controller.signal.aborted) {
          setError('Failed to load your dashboard');
        }
      }
    };

    void load();
    return () => controller.abort();
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-semibold">My dashboard</h1>
      <p className="mt-1 text-content-secondary">Your trips, risk, and application status.</p>

      {error && <p className="mt-6 text-risk-critical">{error}</p>}

      {!error && (
        <>
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <ApplicationStatusPanel application={application} />
            <MyRiskPanel trips={trips} />
          </div>
          <MyTripsPanel trips={trips} />
        </>
      )}
    </div>
  );
}
