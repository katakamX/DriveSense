import { useEffect, useState } from 'react';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { fetchDriverRoster, type RosterDriver } from '@/lib/api/driverRoster';

const STATUS_TONE: Record<string, BadgeTone> = {
  draft: 'neutral',
  pending: 'moderate',
  verified: 'low',
  rejected: 'critical',
};

const STATUS_FILTERS = ['all', 'draft', 'pending', 'verified', 'rejected'] as const;
type StatusFilter = (typeof STATUS_FILTERS)[number];

const FILTER_LABEL: Record<StatusFilter, string> = {
  all: 'All',
  draft: 'Draft',
  pending: 'Pending',
  verified: 'Verified',
  rejected: 'Rejected',
};

export function EmployeeDrivers() {
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [drivers, setDrivers] = useState<RosterDriver[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setDrivers(null);
    setError(null);
    fetchDriverRoster(filter === 'all' ? undefined : filter, controller.signal)
      .then((found) => setDrivers(found))
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Could not load drivers');
        }
      });
    return () => controller.abort();
  }, [filter]);

  return (
    <div>
      <h1 className="text-2xl font-semibold">Drivers</h1>
      <p className="mt-1 text-content-secondary">All onboarded and applicant drivers.</p>

      <div className="mt-4 flex gap-1">
        {STATUS_FILTERS.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setFilter(option)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              filter === option
                ? 'bg-surface-overlay text-content-primary'
                : 'text-content-secondary hover:text-content-primary'
            }`}
          >
            {FILTER_LABEL[option]}
          </button>
        ))}
      </div>

      <Panel className="mt-6 overflow-hidden p-0">
        {error && <p className="p-5 text-risk-critical">{error}</p>}
        {!error && drivers !== null && drivers.length === 0 && (
          <p className="p-5 text-content-muted">No drivers found.</p>
        )}
        {!error && drivers !== null && drivers.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-left text-content-muted">
                <th className="px-5 py-3 font-medium">Name</th>
                <th className="px-5 py-3 font-medium">License #</th>
                <th className="px-5 py-3 font-medium">Code</th>
                <th className="px-5 py-3 font-medium">Vehicle</th>
                <th className="px-5 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {drivers.map((driver) => (
                <tr key={driver.id} className="border-b border-border-subtle last:border-0">
                  <td className="px-5 py-3 text-content-primary">{driver.name}</td>
                  <td className="px-5 py-3 text-content-secondary">{driver.license_number}</td>
                  <td className="px-5 py-3 text-content-secondary">{driver.driver_code ?? '—'}</td>
                  <td className="px-5 py-3 text-content-secondary">
                    {driver.current_vehicle
                      ? `${driver.current_vehicle.make} ${driver.current_vehicle.model}`
                      : '—'}
                  </td>
                  <td className="px-5 py-3">
                    <Badge tone={STATUS_TONE[driver.status] ?? 'neutral'}>{driver.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
