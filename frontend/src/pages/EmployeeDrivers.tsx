import { useEffect, useState } from 'react';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import {
  createDriver,
  fetchDriverRoster,
  type DriverCreateInput,
  type RosterDriver,
} from '@/lib/api/driverRoster';
import { fetchVehicleRoster, type RosterVehicle } from '@/lib/api/vehicleRoster';

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

const INPUT_CLASS =
  'rounded-md border border-border-subtle bg-surface-base px-3 py-1.5 text-sm text-content-primary placeholder:text-content-muted focus:border-accent focus:outline-none';
const BUTTON_CLASS =
  'rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-surface-base transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40';

const EMPTY_FORM = {
  name: '',
  license_number: '',
  date_of_birth: '',
  driver_code: '',
  current_vehicle_id: '',
};

function CreateDriverForm({
  onCreated,
  onCancel,
}: {
  onCreated: (driver: RosterDriver) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [vehicles, setVehicles] = useState<RosterVehicle[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchVehicleRoster(undefined, controller.signal)
      .then(setVehicles)
      .catch(() => {
        // A failed vehicle lookup shouldn't block driver creation — the
        // dropdown just stays empty and the driver can be assigned later.
      });
    return () => controller.abort();
  }, []);

  const handleSubmit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const input: DriverCreateInput = {
        name: form.name,
        license_number: form.license_number,
        date_of_birth: form.date_of_birth,
      };
      if (form.driver_code) input.driver_code = form.driver_code;
      if (form.current_vehicle_id) input.current_vehicle_id = form.current_vehicle_id;
      onCreated(await createDriver(input));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create driver');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Panel className="mt-4 p-5">
      <form onSubmit={(event) => void handleSubmit(event)} className="grid gap-3 sm:grid-cols-5">
        <input
          required
          placeholder="Full name"
          value={form.name}
          onChange={(event) => setForm({ ...form, name: event.target.value })}
          className={INPUT_CLASS}
        />
        <input
          required
          placeholder="License number"
          value={form.license_number}
          onChange={(event) => setForm({ ...form, license_number: event.target.value })}
          className={INPUT_CLASS}
        />
        <input
          required
          type="date"
          aria-label="Date of birth"
          value={form.date_of_birth}
          onChange={(event) => setForm({ ...form, date_of_birth: event.target.value })}
          className={`tabular ${INPUT_CLASS}`}
        />
        <input
          placeholder="Driver code (optional)"
          value={form.driver_code}
          onChange={(event) => setForm({ ...form, driver_code: event.target.value })}
          className={INPUT_CLASS}
        />
        <select
          aria-label="Assign vehicle"
          value={form.current_vehicle_id}
          onChange={(event) => setForm({ ...form, current_vehicle_id: event.target.value })}
          className={INPUT_CLASS}
        >
          <option value="">No vehicle assigned</option>
          {vehicles.map((vehicle) => (
            <option key={vehicle.id} value={vehicle.id}>
              {vehicle.make} {vehicle.model} · {vehicle.license_plate}
            </option>
          ))}
        </select>
        {error && <p className="sm:col-span-5 text-sm text-risk-critical">{error}</p>}
        <div className="flex gap-2 sm:col-span-5">
          <button type="submit" disabled={submitting} className={BUTTON_CLASS}>
            {submitting ? 'Creating…' : 'Create driver'}
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

export function EmployeeDrivers() {
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [drivers, setDrivers] = useState<RosterDriver[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);

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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Drivers</h1>
          <p className="mt-1 text-content-secondary">All onboarded and applicant drivers.</p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate((shown) => !shown)}
          className="rounded-md bg-surface-overlay px-3 py-1.5 text-sm font-medium text-content-primary hover:opacity-90"
        >
          {showCreate ? 'Close' : '+ New driver'}
        </button>
      </div>

      {showCreate && (
        <CreateDriverForm
          onCreated={(driver) => {
            setDrivers((prev) => (prev ? [driver, ...prev] : [driver]));
            setShowCreate(false);
          }}
          onCancel={() => setShowCreate(false)}
        />
      )}

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
