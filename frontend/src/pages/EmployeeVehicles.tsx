import { useEffect, useState } from 'react';

import { Panel } from '@/components/ui/Panel';
import { fetchVehicleRoster, type RosterVehicle } from '@/lib/api/vehicleRoster';

export function EmployeeVehicles() {
  const [makeInput, setMakeInput] = useState('');
  const [make, setMake] = useState('');
  const [vehicles, setVehicles] = useState<RosterVehicle[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setVehicles(null);
    setError(null);
    fetchVehicleRoster(make || undefined, controller.signal)
      .then((found) => setVehicles(found))
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Could not load vehicles');
        }
      });
    return () => controller.abort();
  }, [make]);

  return (
    <div>
      <h1 className="text-2xl font-semibold">Vehicles</h1>
      <p className="mt-1 text-content-secondary">Fleet vehicles.</p>

      <form
        className="mt-4 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setMake(makeInput.trim());
        }}
      >
        <input
          type="text"
          value={makeInput}
          onChange={(event) => setMakeInput(event.target.value)}
          placeholder="Filter by make"
          className="rounded-md border border-border-subtle bg-surface-base px-3 py-1.5 text-sm text-content-primary placeholder:text-content-muted"
        />
        <button
          type="submit"
          className="rounded-md bg-surface-overlay px-3 py-1.5 text-sm font-medium text-content-primary hover:opacity-90"
        >
          Filter
        </button>
        {make && (
          <button
            type="button"
            onClick={() => {
              setMakeInput('');
              setMake('');
            }}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-content-secondary hover:text-content-primary"
          >
            Clear
          </button>
        )}
      </form>

      <Panel className="mt-6 overflow-hidden p-0">
        {error && <p className="p-5 text-risk-critical">{error}</p>}
        {!error && vehicles !== null && vehicles.length === 0 && (
          <p className="p-5 text-content-muted">No vehicles found.</p>
        )}
        {!error && vehicles !== null && vehicles.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-left text-content-muted">
                <th className="px-5 py-3 font-medium">Make</th>
                <th className="px-5 py-3 font-medium">Model</th>
                <th className="px-5 py-3 font-medium">Year</th>
                <th className="px-5 py-3 font-medium">VIN</th>
                <th className="px-5 py-3 font-medium">License plate</th>
              </tr>
            </thead>
            <tbody>
              {vehicles.map((vehicle) => (
                <tr key={vehicle.id} className="border-b border-border-subtle last:border-0">
                  <td className="px-5 py-3 text-content-primary">{vehicle.make}</td>
                  <td className="px-5 py-3 text-content-secondary">{vehicle.model}</td>
                  <td className="tabular px-5 py-3 text-content-secondary">{vehicle.year}</td>
                  <td className="tabular px-5 py-3 text-content-secondary">{vehicle.vin}</td>
                  <td className="px-5 py-3 text-content-secondary">{vehicle.license_plate}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
