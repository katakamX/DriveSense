/** Resolves `/auth/me` once and shares the answer.
 *
 * Both the nav bar and the route guards need the caller's role, and before
 * this existed `Home.tsx` fetched it on its own. Resolving it in one place
 * keeps that to a single request per page load and, more importantly, keeps
 * every consumer agreeing about who is logged in.
 */

import { useEffect, useState, type ReactNode } from 'react';

import { me } from '@/lib/api/auth';
import { SessionContext, type SessionState } from '@/lib/auth/session';

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<SessionState>({ status: 'loading' });

  useEffect(() => {
    let cancelled = false;
    me()
      .then((user) => {
        if (!cancelled) setState({ status: 'authenticated', user });
      })
      .catch(() => {
        // A 401 is the normal answer for a signed-out visitor, not an error
        // worth surfacing — the login pages render for exactly this state.
        if (!cancelled) setState({ status: 'anonymous' });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return <SessionContext.Provider value={state}>{children}</SessionContext.Provider>;
}
