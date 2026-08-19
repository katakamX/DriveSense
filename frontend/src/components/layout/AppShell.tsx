import { Gauge } from 'lucide-react';
import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';

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
            <NavLink to="/" end className={navLinkClassName}>
              Dashboard
            </NavLink>
            <NavLink to="/driver-monitor" className={navLinkClassName}>
              Driver Monitor
            </NavLink>
            <NavLink to="/become-a-driver" className={navLinkClassName}>
              Become a Driver
            </NavLink>
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
            <NavLink to="/admin/users" className={navLinkClassName}>
              Users
            </NavLink>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
    </div>
  );
}
