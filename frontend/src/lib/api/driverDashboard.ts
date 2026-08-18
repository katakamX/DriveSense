/** Typed client for the driver-facing self-service dashboard (M12). */

export interface MyTrip {
  id: string;
  driver_id: string;
  vehicle_id: string;
  started_at: string;
  ended_at: string | null;
  distance_km: number | null;
  status: string;
  speed_limit_kph: number | null;
  risk_score: number | null;
  risk_band: string | null;
  risk_engine_version: string | null;
  created_at: string;
  updated_at: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

async function failure(response: Response): Promise<Error> {
  const detail = await response
    .json()
    .then((data: { detail?: string }) => data.detail)
    .catch(() => undefined);
  return new Error(detail ?? `Request failed with status ${response.status}`);
}

/** The current user's trips, or `[]` when they have no driver record yet. */
export async function fetchMyTrips(signal?: AbortSignal): Promise<MyTrip[]> {
  const response = await fetch(`${API_BASE}/trips/me`, { credentials: 'include', signal });
  if (response.status === 404) return [];
  if (!response.ok) throw await failure(response);
  return (await response.json()) as MyTrip[];
}
