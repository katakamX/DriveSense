import { Gauge } from 'lucide-react';
import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';

import { isAdmin, isStaff, useSession } from '@/lib/auth/session';

interface AppShellProps {
  children: ReactNode;
}

function navLinkClassName({ isActive }: { isActive: boolean }): string {
  const base = 'rounded-md px-3 py-1.5 text-sm font-medium transition-colors';
  return isActive
    ? `${base} bg-surface-overlay text-content-primary`
    : `${base} text-content-secondary hover:text-content-primary`;
}

export function AppShell({ children }: AppShellProps) {
  const session = useSession();
  const role = session.status === 'authenticated' ? session.user.role : null;
  // Signed out, or still resolving: draw no links rather than flashing a set
  // that may not survive the answer. The login pages need no nav.
  const staff = role !== null && isStaff(role);
  const admin = role !== null && isAdmin(role);

  return (
    <div className="min-h-screen bg-surface-base text-content-primary">
      <header className="border-b border-border-subtle">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-4">
          <div className="flex items-center gap-2.5">
            <Gauge className="h-5 w-5 text-accent" aria-hidden="true" />
            <span className="text-sm font-medium uppercase tracking-[0.2em] text-content-secondary">
              DriveSense
            </span>
          </div>
          <nav className="flex items-center gap-1">
            {role !== null && (
              <>
                <NavLink to="/" end className={navLinkClassName}>
                  Dashboard
                </NavLink>
                <NavLink to="/driver-monitor" className={navLinkClassName}>
                  Driver Monitor
                </NavLink>
                <NavLink to="/become-a-driver" className={navLinkClassName}>
                  Become a Driver
                </NavLink>
              </>
            )}
            {staff && (
              <>
                <NavLink to="/employee/review" className={navLinkClassName}>
                  Review Applications
                </NavLink>
                <NavLink to="/employee/drivers" className={navLinkClassName}>
                  Drivers
                </NavLink>
                <NavLink to="/employee/vehicles" className={navLinkClassName}>
                  Vehicles
                </NavLink>
                <NavLink to="/employee/trips" className={navLinkClassName}>
                  Trips
                </NavLink>
              </>
            )}
            {admin && (
              <>
                <NavLink to="/admin/users" className={navLinkClassName}>
                  Users
                </NavLink>
                <NavLink to="/admin/system" className={navLinkClassName}>
                  System
                </NavLink>
              </>
            )}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  );
}
