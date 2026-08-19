/** Typed client for admin user/role management (`/users`, admin-only). */

export interface AdminUser {
  id: string;
  email: string;
  role: string;
  email_verified: boolean;
  created_at: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

async function failure(response: Response): Promise<Error> {
  const detail = await response
    .json()
    .then((data: { detail?: string }) => data.detail)
    .catch(() => undefined);
  return new Error(detail ?? `Request failed with status ${response.status}`);
}

export async function fetchUsers(signal?: AbortSignal): Promise<AdminUser[]> {
  const response = await fetch(`${API_BASE}/users`, { credentials: 'include', signal });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as AdminUser[];
}

export async function updateUserRole(userId: string, role: string): Promise<AdminUser> {
  const response = await fetch(`${API_BASE}/users/${userId}/role`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ role }),
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as AdminUser;
}
