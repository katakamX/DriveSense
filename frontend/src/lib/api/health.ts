/**
 * Typed client for the backend health endpoints.
 *
 * From Milestone 3 these types are generated from the backend's OpenAPI
 * schema (shared/contracts) rather than hand-written, which removes an entire
 * class of frontend/backend drift. Health is small enough to hand-write now.
 */

export interface HealthResponse {
  status: 'ok';
  service: string;
  version: string;
  environment: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`, { signal });
  if (!response.ok) {
    throw new Error(`Health check failed with status ${response.status}`);
  }
  return (await response.json()) as HealthResponse;
}
