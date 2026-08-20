import { useEffect, useState } from 'react';

import { Panel } from '@/components/ui/Panel';
import {
  createVehicle,
  fetchVehicleRoster,
  type RosterVehicle,
  type VehicleCreateInput,
} from '@/lib/api/vehicleRoster';

const INPUT_CLASS =
  'rounded-md border border-border-subtle bg-surface-base px-3 py-1.5 text-sm text-content-primary placeholder:text-content-muted focus:border-accent focus:outline-none';
const BUTTON_CLASS =
  'rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-surface-base transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40';

const EMPTY_FORM: VehicleCreateInput = {
  make: '',
  model: '',
  year: new Date().getFullYear(),
  vin: '',
  license_plate: '',
};

function CreateVehicleForm({
  onCreated,
  onCancel,
}: {
  onCreated: (vehicle: RosterVehicle) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<VehicleCreateInput>(EMPTY_FORM);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      onCreated(await createVehicle(form));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create vehicle');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Panel className="mt-4 p-5">
      <form onSubmit={(event) => void handleSubmit(event)} className="grid gap-3 sm:grid-cols-5">
        <input
          required
          placeholder="Make"
          value={form.make}
          onChange={(event) => setForm({ ...form, make: event.target.value })}
          className={INPUT_CLASS}
        />
        <input
          required
          placeholder="Model"
          value={form.model}
          onChange={(event) => setForm({ ...form, model: event.target.value })}
          className={INPUT_CLASS}
        />
        <input
          required
          type="number"
          placeholder="Year"
          value={form.year}
          onChange={(event) => setForm({ ...form, year: Number(event.target.value) })}
          className={`tabular ${INPUT_CLASS}`}
        />
        <input
          required
          placeholder="VIN"
          value={form.vin}
          onChange={(event) => setForm({ ...form, vin: event.target.value })}
          className={`tabular ${INPUT_CLASS}`}
        />
        <input
          required
          placeholder="License plate"
          value={form.license_plate}
          onChange={(event) => setForm({ ...form, license_plate: event.target.value })}
          className={INPUT_CLASS}
        />
        {error && <p className="sm:col-span-5 text-sm text-risk-critical">{error}</p>}
        <div className="flex gap-2 sm:col-span-5">
          <button type="submit" disabled={submitting} className={BUTTON_CLASS}>
            {submitting ? 'Creating…' : 'Create vehicle'}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md px-3 py-1.5 text-sm font-medium text-content-secondary hover:text-content-primary"
          >
            Cancel
          </button>
        </div>
      </form>
    </Panel>
  );
}

export function EmployeeVehicles() {
  const [makeInput, setMakeInput] = useState('');
  const [make, setMake] = useState('');
  const [vehicles, setVehicles] = useState<RosterVehicle[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Vehicles</h1>
          <p className="mt-1 text-content-secondary">Fleet vehicles.</p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate((shown) => !shown)}
          className="rounded-md bg-surface-overlay px-3 py-1.5 text-sm font-medium text-content-primary hover:opacity-90"
        >
          {showCreate ? 'Close' : '+ New vehicle'}
        </button>
      </div>

      {showCreate && (
        <CreateVehicleForm
          onCreated={(vehicle) => {
            setVehicles((prev) => (prev ? [vehicle, ...prev] : [vehicle]));
            setShowCreate(false);
          }}
          onCancel={() => setShowCreate(false)}
        />
      )}

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
