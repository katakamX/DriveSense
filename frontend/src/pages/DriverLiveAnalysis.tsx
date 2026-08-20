import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { fetchDriver, type RosterDriver } from '@/lib/api/driverRoster';

const STATUS_TONE: Record<string, BadgeTone> = {
  draft: 'neutral',
  pending: 'moderate',
  verified: 'low',
  rejected: 'critical',
};

export function DriverLiveAnalysis() {
  const { driverId } = useParams<{ driverId: string }>();
  const [driver, setDriver] = useState<RosterDriver | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!driverId) return;
    const controller = new AbortController();
    setDriver(null);
    setError(null);
    fetchDriver(driverId, controller.signal)
      .then(setDriver)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Could not load driver');
        }
      });
    return () => controller.abort();
  }, [driverId]);

  return (
    <div>
      <Link to="/employee/drivers" className="text-sm text-content-secondary hover:underline">
        ← Back to drivers
      </Link>

      {error && <p className="mt-4 text-risk-critical">{error}</p>}

      {!error && driver === null && <p className="mt-4 text-content-muted">Loading…</p>}

      {!error && driver !== null && (
        <>
          <div className="mt-2 flex items-center justify-between">
            <div>
              <h1 className="font-display text-2xl font-semibold tracking-display">
                {driver.name}
              </h1>
              <p className="mt-1 text-content-secondary">
                Driver Live Analysis · {driver.license_number}
                {driver.driver_code && ` · ${driver.driver_code}`}
              </p>
            </div>
            <Badge tone={STATUS_TONE[driver.status] ?? 'neutral'}>{driver.status}</Badge>
          </div>

          <Panel className="mt-6 p-5">
            <p className="text-content-secondary">
              Vehicle:{' '}
              {driver.current_vehicle
                ? `${driver.current_vehicle.make} ${driver.current_vehicle.model} · ${driver.current_vehicle.license_plate}`
                : 'No vehicle assigned'}
            </p>
          </Panel>
        </>
      )}
    </div>
  );
}
