/** Typed client for the admin system-health endpoint (`/admin/system-health`). */

export interface SystemHealth {
  risk_engine_version: string;
  model_version: string | null;
  model_loaded: boolean;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export async function fetchSystemHealth(signal?: AbortSignal): Promise<SystemHealth> {
  const response = await fetch(`${API_BASE}/admin/system-health`, {
    credentials: 'include',
    signal,
  });
  if (!response.ok) {
    throw new Error(`Request to /admin/system-health failed with status ${response.status}`);
  }
  return (await response.json()) as SystemHealth;
}
