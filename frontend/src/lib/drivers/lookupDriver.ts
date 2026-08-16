/**
 * Driver lookup by code, via `GET /api/v1/drivers?code=`.
 *
 * The backend normalises `driver_code` to upper case on write and the filter
 * does an exact match against that, so the client upper-cases too — the
 * point is that the caller can type either case, not that the server does
 * fuzzy matching.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export interface Driver {
  driverCode: string;
  name: string;
  vehicle: string;
  licencePlate: string;
  shiftStartedAt: string;
}

export class DriverNotFoundError extends Error {
  constructor(code: string) {
    super(`No driver found with code ${code}`);
    this.name = 'DriverNotFoundError';
  }
}

interface DriverVehicleRead {
  id: string;
  make: string;
  model: string;
  license_plate: string;
}

interface DriverRead {
  id: string;
  name: string;
  license_number: string;
  date_of_birth: string;
  driver_code: string | null;
  current_vehicle: DriverVehicleRead | null;
  created_at: string;
  updated_at: string;
}

export async function lookupDriver(code: string): Promise<Driver> {
  const normalised = code.trim().toUpperCase();
  if (!normalised) {
    throw new DriverNotFoundError(normalised);
  }

  const response = await fetch(
    `${API_BASE}/drivers?${new URLSearchParams({ code: normalised }).toString()}`,
  );
  if (!response.ok) {
    throw new Error(`Driver lookup failed with status ${response.status}`);
  }

  const found = (await response.json()) as DriverRead[];
  const driver = found[0];
  if (!driver) {
    throw new DriverNotFoundError(normalised);
  }

  return {
    driverCode: driver.driver_code ?? normalised,
    name: driver.name,
    vehicle: driver.current_vehicle
      ? `${driver.current_vehicle.make} ${driver.current_vehicle.model}`
      : 'No vehicle assigned',
    licencePlate: driver.current_vehicle?.license_plate ?? '—',
    // Shift start isn't modelled yet — nothing tracks when a driver clocked
    // on. `created_at` on the driver record isn't that, so this stays now()
    // until there's a real source, same trade-off the mock made.
    shiftStartedAt: new Date().toISOString(),
  };
}
