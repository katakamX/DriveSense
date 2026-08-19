import { Navigate } from 'react-router-dom';

import { isStaff, useSession } from '@/lib/auth/session';
import { Dashboard } from '@/pages/Dashboard';

/** `/` is a role fork, not a page: staff land on the trips-wide Dashboard,
 * everyone else (drivers, or anyone not logged in) is sent to their own view
 * rather than shown staff data.
 */
export function Home() {
  const session = useSession();

  if (session.status === 'loading') return null;
  if (session.status === 'anonymous') return <Navigate to="/login" replace />;
  if (isStaff(session.user.role)) return <Dashboard />;
  return <Navigate to="/dashboard" replace />;
}
