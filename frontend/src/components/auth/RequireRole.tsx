/** Route guard: send the wrong role somewhere sensible instead of letting the
 * page render and fail with a raw API error.
 *
 * Redirects rather than rendering a "forbidden" screen — a driver who lands on
 * `/admin/users` by typing the URL has no use for that page, and `/` already
 * forks each role to the view it does have. The backend still enforces the
 * real gate; this only decides what the browser draws.
 */

import type { ReactNode } from 'react';
import { Navigate } from 'react-router-dom';

import { isAdmin, isStaff, useSession } from '@/lib/auth/session';

interface RequireRoleProps {
  allow: 'staff' | 'admin';
  children: ReactNode;
}

export function RequireRole({ allow, children }: RequireRoleProps) {
  const session = useSession();

  // Nothing is known yet. Rendering the children here would fire their API
  // calls before we know whether the caller may see them at all.
  if (session.status === 'loading') return null;
  if (session.status === 'anonymous') return <Navigate to="/login" replace />;

  const permitted = allow === 'admin' ? isAdmin(session.user.role) : isStaff(session.user.role);
  if (!permitted) return <Navigate to="/" replace />;

  return <>{children}</>;
}
