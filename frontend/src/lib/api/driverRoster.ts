/** Typed client for the staff driver roster (`GET /drivers`, staff-only). */

export interface RosterDriver {
  id: string;
  name: string;
  license_number: string;
  driver_code: string | null;
  status: string;
  current_vehicle: { id: string; make: string; model: string; license_plate: string } | null;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export async function fetchDriverRoster(
  status?: string,
  signal?: AbortSignal,
): Promise<RosterDriver[]> {
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  const query = params.toString();
  const response = await fetch(`${API_BASE}/drivers${query ? `?${query}` : ''}`, { signal });
  if (!response.ok) {
    throw new Error(`Request to /drivers failed with status ${response.status}`);
  }
  return (await response.json()) as RosterDriver[];
}
