import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import {
  fetchDrivers,
  fetchTrips,
  fetchVehicles,
  type Driver,
  type Trip,
  type Vehicle,
} from '@/lib/api/trips';

const STATUS_TONE: Record<string, BadgeTone> = {
  in_progress: 'moderate',
  completed: 'low',
};

export function Dashboard() {
  const [trips, setTrips] = useState<Trip[]>([]);
  const [drivers, setDrivers] = useState<Record<string, Driver>>({});
  const [vehicles, setVehicles] = useState<Record<string, Vehicle>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    const load = async (): Promise<void> => {
      try {
        const [tripList, driverList, vehicleList] = await Promise.all([
          fetchTrips(controller.signal),
          fetchDrivers(controller.signal),
          fetchVehicles(controller.signal),
        ]);
        setTrips(tripList);
        setDrivers(Object.fromEntries(driverList.map((driver) => [driver.id, driver])));
        setVehicles(Object.fromEntries(vehicleList.map((vehicle) => [vehicle.id, vehicle])));
      } catch {
        if (!controller.signal.aborted) {
          setError('Failed to load trips');
        }
      }
    };

    void load();
    return () => controller.abort();
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-semibold">Trips</h1>
      <p className="mt-1 text-content-secondary">All recorded trips.</p>

      <Panel className="mt-6 overflow-hidden p-0">
        {error && <p className="p-5 text-risk-critical">{error}</p>}
        {!error && trips.length === 0 && <p className="p-5 text-content-muted">No trips yet.</p>}
        {!error && trips.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-left text-content-muted">
                <th className="px-5 py-3 font-medium">Driver</th>
                <th className="px-5 py-3 font-medium">Vehicle</th>
                <th className="px-5 py-3 font-medium">Status</th>
                <th className="px-5 py-3 font-medium">Started</th>
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
                    <td className="px-5 py-3 text-right">
                      <Link
                        to={`/trips/${trip.id}/live`}
                        className="text-content-primary underline decoration-content-muted underline-offset-4 transition-colors hover:decoration-content-primary"
                      >
                        Live Drive →
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
