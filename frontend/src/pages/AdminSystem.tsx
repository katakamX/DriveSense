import { useEffect, useState } from 'react';

import { Badge } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { StatTile } from '@/components/ui/StatTile';
import { fetchSystemHealth, type SystemHealth } from '@/lib/api/systemHealth';

export function AdminSystem() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchSystemHealth(controller.signal)
      .then((found) => setHealth(found))
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Could not load system health');
        }
      });
    return () => controller.abort();
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-semibold">System</h1>
      <p className="mt-1 text-content-secondary">
        Currently running risk engine and model versions.
      </p>

      <Panel className="mt-6 p-6">
        {error && <p className="text-risk-critical">{error}</p>}
        {!error && health === null && <p className="text-content-muted">Loading…</p>}
        {!error && health !== null && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <StatTile label="Risk engine version" value={health.risk_engine_version} />
            <div className="rounded-lg border border-border-subtle bg-surface-raised p-4">
              <div className="text-xs uppercase tracking-[0.15em] text-content-muted">
                Model version
              </div>
              <div className="mt-1 flex items-center gap-2">
                <span className="tabular text-2xl font-semibold text-content-primary">
                  {health.model_version ?? '—'}
                </span>
                <Badge tone={health.model_loaded ? 'low' : 'neutral'}>
                  {health.model_loaded ? 'Loaded' : 'Rule-only'}
                </Badge>
              </div>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
