import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { fetchEmployeeTrips, type EmployeeTrip } from '@/lib/api/employeeTrips';
import { fetchDrivers, fetchVehicles, type Driver, type Vehicle } from '@/lib/api/trips';

const STATUS_TONE: Record<string, BadgeTone> = {
  in_progress: 'moderate',
  completed: 'low',
};

const RISK_BAND_TONE: Record<string, BadgeTone> = {
  CALM: 'low',
  NORMAL: 'neutral',
  AGGRESSIVE: 'high',
  HIGH_RISK: 'critical',
};

const SORT_OPTIONS = [
  { value: '', label: 'Newest first' },
  { value: '-risk_score', label: 'Highest risk first' },
  { value: 'risk_score', label: 'Lowest risk first' },
] as const;

export function EmployeeTrips() {
  const [sort, setSort] = useState('');
  const [trips, setTrips] = useState<EmployeeTrip[] | null>(null);
  const [drivers, setDrivers] = useState<Record<string, Driver>>({});
  const [vehicles, setVehicles] = useState<Record<string, Vehicle>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setTrips(null);
    setError(null);

    const load = async (): Promise<void> => {
      try {
        const [tripList, driverList, vehicleList] = await Promise.all([
          fetchEmployeeTrips(sort || undefined, controller.signal),
          fetchDrivers(controller.signal),
          fetchVehicles(controller.signal),
        ]);
        setTrips(tripList);
        setDrivers(Object.fromEntries(driverList.map((driver) => [driver.id, driver])));
        setVehicles(Object.fromEntries(vehicleList.map((vehicle) => [vehicle.id, vehicle])));
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Could not load trips');
        }
      }
    };

    void load();
    return () => controller.abort();
  }, [sort]);

  return (
    <div>
      <h1 className="text-2xl font-semibold">Trips</h1>
      <p className="mt-1 text-content-secondary">All recorded trips, sortable by risk.</p>

      <div className="mt-4">
        <select
          value={sort}
          onChange={(event) => setSort(event.target.value)}
          className="rounded-md border border-border-subtle bg-surface-base px-3 py-1.5 text-sm text-content-primary"
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      <Panel className="mt-6 overflow-hidden p-0">
        {error && <p className="p-5 text-risk-critical">{error}</p>}
        {!error && trips !== null && trips.length === 0 && (
          <p className="p-5 text-content-muted">No trips yet.</p>
        )}
        {!error && trips !== null && trips.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-left text-content-muted">
                <th className="px-5 py-3 font-medium">Driver</th>
                <th className="px-5 py-3 font-medium">Vehicle</th>
                <th className="px-5 py-3 font-medium">Status</th>
                <th className="px-5 py-3 font-medium">Started</th>
                <th className="px-5 py-3 font-medium">Risk</th>
                <th className="px-5 py-3 font-medium" aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {trips.map((trip) => {
                const driver = drivers[trip.driver_id];
                const vehicle = vehicles[trip.vehicle_id];
                return (
                  <tr key={trip.id} className="border-b border-border-subtle last:border-0">
                    <td className="px-5 py-3 text-content-primary">
                      {driver?.name ?? trip.driver_id}
                    </td>
                    <td className="px-5 py-3 text-content-secondary">
                      {vehicle ? `${vehicle.make} ${vehicle.model}` : trip.vehicle_id}
                    </td>
                    <td className="px-5 py-3">
                      <Badge tone={STATUS_TONE[trip.status] ?? 'neutral'}>{trip.status}</Badge>
                    </td>
                    <td className="tabular px-5 py-3 text-content-secondary">
                      {new Date(trip.started_at).toLocaleString()}
                    </td>
                    <td className="px-5 py-3">
                      {trip.risk_band === null ? (
                        <span className="text-content-muted">—</span>
                      ) : (
                        <Badge tone={RISK_BAND_TONE[trip.risk_band] ?? 'neutral'}>
                          {trip.risk_score !== null ? trip.risk_score.toFixed(1) : trip.risk_band}
                        </Badge>
                      )}
                    </td>
                    <td className="px-5 py-3 text-right">
                      <Link
                        to={`/trips/${trip.id}`}
                        className="text-content-primary underline decoration-content-muted underline-offset-4 transition-colors hover:decoration-content-primary"
                      >
                        Details →
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
