/** Typed client for the staff-side driver-application review endpoints (M-Auth-4). */

import type { DriverApplicationRead } from '@/lib/api/driverApplication';

export interface DriverApplicationSummary {
  id: string;
  name: string;
  license_number: string;
  status: 'draft' | 'pending' | 'verified' | 'rejected';
  created_at: string;
  documents_uploaded: number;
  documents_required: number;
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: 'include', ...init });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

/** The review queue. `status` is omitted to list every application. */
export function listApplications(status?: string): Promise<DriverApplicationSummary[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : '';
  return request(`/driver-review/applications${query}`);
}

export function getApplication(driverId: string): Promise<DriverApplicationRead> {
  return request(`/driver-review/applications/${driverId}`);
}

export function verifyApplication(driverId: string): Promise<DriverApplicationRead> {
  return request(`/driver-review/applications/${driverId}/verify`, { method: 'POST' });
}

export function rejectApplication(driverId: string): Promise<DriverApplicationRead> {
  return request(`/driver-review/applications/${driverId}/reject`, { method: 'POST' });
}

/** URL for a document's raw bytes — an `<img>`/`<a>` target, not fetched via `request`. */
export function documentFileUrl(driverId: string, documentId: string): string {
  return `${API_BASE}/driver-review/applications/${driverId}/documents/${documentId}/file`;
}
