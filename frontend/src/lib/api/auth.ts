/** Typed client for the email/password + OTP auth endpoints. */

export interface UserRead {
  id: string;
  email: string;
  role: string;
  email_verified: boolean;
  created_at: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const detail = await response
      .json()
      .then((data: { detail?: string }) => data.detail)
      .catch(() => undefined);
    throw new Error(detail ?? `Request failed with status ${response.status}`);
  }
  return response.status === 204 ? (undefined as T) : ((await response.json()) as T);
}

export function register(email: string, password: string): Promise<UserRead> {
  return postJson('/auth/register', { email, password });
}

export function login(email: string, password: string): Promise<UserRead> {
  return postJson('/auth/login', { email, password });
}

export function logout(): Promise<void> {
  return postJson('/auth/logout', undefined);
}

export function verifyOtp(email: string, code: string): Promise<UserRead> {
  return postJson('/auth/verify-otp', { email, code });
}

export function me(): Promise<UserRead> {
  return fetch(`${API_BASE}/auth/me`, { credentials: 'include' }).then((response) => {
    if (!response.ok) throw new Error('Not authenticated');
    return response.json() as Promise<UserRead>;
  });
}
