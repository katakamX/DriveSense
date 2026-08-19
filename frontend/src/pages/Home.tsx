import { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';

import { me } from '@/lib/api/auth';
import { Dashboard } from '@/pages/Dashboard';

type HomeState =
  { status: 'loading' } | { status: 'staff' } | { status: 'driver' } | { status: 'anon' };

/** `/` is a role fork, not a page: staff land on the trips-wide Dashboard,
 * everyone else (drivers, or anyone not logged in) is sent to their own view
 * rather than shown staff data.
 */
export function Home() {
  const [state, setState] = useState<HomeState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    me()
      .then((user) => {
        if (cancelled) return;
        setState({
          status: user.role === 'employee' || user.role === 'admin' ? 'staff' : 'driver',
        });
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'anon' });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === 'loading') return null;
  if (state.status === 'staff') return <Dashboard />;
  if (state.status === 'driver') return <Navigate to="/dashboard" replace />;
  return <Navigate to="/login" replace />;
}
