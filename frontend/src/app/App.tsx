import { Activity, Gauge } from 'lucide-react';

import { useHealth } from '@/lib/api/useHealth';

const CONNECTION_LABEL: Record<string, { text: string; dot: string }> = {
  checking: { text: 'Checking backend', dot: 'bg-content-muted' },
  connected: { text: 'Backend connected', dot: 'bg-risk-low' },
  unreachable: { text: 'Backend unreachable', dot: 'bg-risk-critical' },
};

/**
 * Milestone 1 shell. Its only job is to prove the frontend builds, renders,
 * and can reach the backend. Routing and the eight product pages arrive with
 * Milestone 6.
 */
export function App() {
  const { state, data } = useHealth();
  const label = CONNECTION_LABEL[state] ?? CONNECTION_LABEL['checking']!;

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      <div className="w-full max-w-xl">
        <div className="mb-10 flex items-center gap-3">
          <Gauge className="h-6 w-6 text-accent" aria-hidden="true" />
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-content-secondary">
            DriveSense
          </span>
        </div>

        <h1 className="text-4xl font-semibold leading-tight tracking-tight">
          AI-powered driver
          <br />
          intelligence platform
        </h1>

        <p className="mt-4 max-w-md text-content-secondary">
          Project scaffold is running. Telemetry ingest, driving-event detection, driver monitoring
          and the risk engine arrive in later milestones.
        </p>

        <section
          className="mt-10 rounded-lg border border-border-subtle bg-surface-raised p-5"
          aria-label="System status"
        >
          <div className="flex items-center gap-2.5">
            <span className={`h-2 w-2 rounded-full ${label.dot}`} aria-hidden="true" />
            <span className="text-sm text-content-primary">{label.text}</span>
          </div>

          {data && (
            <dl className="mt-4 grid grid-cols-2 gap-y-3 border-t border-border-subtle pt-4 text-sm">
              <dt className="text-content-muted">Service</dt>
              <dd className="tabular text-right text-content-secondary">{data.service}</dd>
              <dt className="text-content-muted">Version</dt>
              <dd className="tabular text-right text-content-secondary">{data.version}</dd>
              <dt className="text-content-muted">Environment</dt>
              <dd className="tabular text-right text-content-secondary">{data.environment}</dd>
            </dl>
          )}
        </section>

        <p className="mt-6 flex items-center gap-2 text-xs text-content-muted">
          <Activity className="h-3.5 w-3.5" aria-hidden="true" />
          Milestone 1 — architecture, scaffold, Docker skeleton, CI
        </p>
      </div>
    </main>
  );
}
