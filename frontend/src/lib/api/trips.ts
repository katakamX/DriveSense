/**
 * Typed REST client for the trip list. Fetches drivers and vehicles
 * alongside trips so the Dashboard can render names, not raw IDs — the
 * backend doesn't expose a joined endpoint, so the join happens here.
 */

export interface Trip {
  id: string;
  driver_id: string;
  vehicle_id: string;
  started_at: string;
  ended_at: string | null;
  distance_km: number | null;
  status: string;
  speed_limit_kph: number | null;
  created_at: string;
  updated_at: string;
}

export interface Driver {
  id: string;
  name: string;
  license_number: string;
  date_of_birth: string;
}

export interface Vehicle {
  id: string;
  make: string;
  model: string;
  year: number;
  vin: string;
  license_plate: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

async function fetchJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { signal });
  if (!response.ok) {
    throw new Error(`Request to ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchTrips(signal?: AbortSignal): Promise<Trip[]> {
  return fetchJson<Trip[]>('/trips', signal);
}

export function fetchDrivers(signal?: AbortSignal): Promise<Driver[]> {
  return fetchJson<Driver[]>('/drivers', signal);
}

export function fetchVehicles(signal?: AbortSignal): Promise<Vehicle[]> {
  return fetchJson<Vehicle[]>('/vehicles', signal);
}
