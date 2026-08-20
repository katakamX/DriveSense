/** Typed client for the staff driver roster (`GET/POST /drivers`, staff-only). */

export interface RosterDriver {
  id: string;
  name: string;
  license_number: string;
  driver_code: string | null;
  status: string;
  current_vehicle: { id: string; make: string; model: string; license_plate: string } | null;
}

export interface DriverCreateInput {
  name: string;
  license_number: string;
  date_of_birth: string;
  driver_code?: string;
  current_vehicle_id?: string;
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

export async function fetchDriverRoster(
  status?: string,
  signal?: AbortSignal,
): Promise<RosterDriver[]> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  const query = params.toString();
  const response = await fetch(`${API_BASE}/drivers${query ? `?${query}` : ''}`, {
    credentials: 'include',
    signal,
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as RosterDriver[];
}

export async function createDriver(input: DriverCreateInput): Promise<RosterDriver> {
  const response = await fetch(`${API_BASE}/drivers`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as RosterDriver;
}
