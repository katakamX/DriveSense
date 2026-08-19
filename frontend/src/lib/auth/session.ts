/** The logged-in user's session: context, hook and role predicates.
 *
 * The provider component lives in `SessionProvider.tsx` rather than here so
 * this module exports no components — mixing the two in one file costs the
 * dev server its fast refresh.
 *
 * Roles here are a UI convenience, never an access control boundary: the
 * backend gates every route it serves, so a tampered role changes which links
 * are drawn, not what the API will return.
 */

import { createContext, useContext } from 'react';

import type { UserRead } from '@/lib/api/auth';

export type SessionState =
  { status: 'loading' } | { status: 'authenticated'; user: UserRead } | { status: 'anonymous' };

export const SessionContext = createContext<SessionState>({ status: 'loading' });

export function useSession(): SessionState {
  return useContext(SessionContext);
}

export function isStaff(role: string): boolean {
  return role === 'employee' || role === 'admin';
}

export function isAdmin(role: string): boolean {
  return role === 'admin';
}
