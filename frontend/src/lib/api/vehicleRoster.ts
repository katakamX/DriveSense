/** Typed client for the staff vehicle roster (`GET /vehicles`, staff-only). */

export interface RosterVehicle {
  id: string;
  make: string;
  model: string;
  year: number;
  vin: string;
  license_plate: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export async function fetchVehicleRoster(
  make?: string,
  signal?: AbortSignal,
): Promise<RosterVehicle[]> {
  const params = new URLSearchParams();
  if (make) params.set('make', make);
  const query = params.toString();
  const response = await fetch(`${API_BASE}/vehicles${query ? `?${query}` : ''}`, { signal });
  if (!response.ok) {
    throw new Error(`Request to /vehicles failed with status ${response.status}`);
  }
  return (await response.json()) as RosterVehicle[];
}
