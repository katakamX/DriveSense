/** Typed client for the staff vehicle roster (`GET/POST /vehicles`, staff-only). */

export interface RosterVehicle {
  id: string;
  make: string;
  model: string;
  year: number;
  vin: string;
  license_plate: string;
}

export interface VehicleCreateInput {
  make: string;
  model: string;
  year: number;
  vin: string;
  license_plate: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

/** The backend's `detail` string if there is one, else a status-code fallback. */
async function failure(response: Response): Promise<Error> {
  const detail = await response
    .json()
    .then((data: { detail?: string }) => data.detail)
    .catch(() => undefined);
  return new Error(detail ?? `Request failed with status ${response.status}`);
}

export async function fetchVehicleRoster(
  make?: string,
  signal?: AbortSignal,
): Promise<RosterVehicle[]> {
  const params = new URLSearchParams();
  if (make) params.set('make', make);
  const query = params.toString();
  const response = await fetch(`${API_BASE}/vehicles${query ? `?${query}` : ''}`, {
    credentials: 'include',
    signal,
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as RosterVehicle[];
}

export async function createVehicle(input: VehicleCreateInput): Promise<RosterVehicle> {
  const response = await fetch(`${API_BASE}/vehicles`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as RosterVehicle;
}
