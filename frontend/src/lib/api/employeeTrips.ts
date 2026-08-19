/** Typed client for the staff trips overview (`GET /trips`, staff-only). */

export interface EmployeeTrip {
  id: string;
  driver_id: string;
  vehicle_id: string;
  started_at: string;
  ended_at: string | null;
  status: string;
  risk_score: number | null;
  risk_band: string | null;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export async function fetchEmployeeTrips(
  sort?: string,
  signal?: AbortSignal,
): Promise<EmployeeTrip[]> {
  const params = new URLSearchParams();
  if (sort) params.set('sort', sort);
  const query = params.toString();
  const response = await fetch(`${API_BASE}/trips${query ? `?${query}` : ''}`, { signal });
  if (!response.ok) {
    throw new Error(`Request to /trips failed with status ${response.status}`);
  }
  return (await response.json()) as EmployeeTrip[];
}
