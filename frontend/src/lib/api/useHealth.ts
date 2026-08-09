import { useEffect, useState } from 'react';

import { fetchHealth, type HealthResponse } from '@/lib/api/health';

export type ConnectionState = 'checking' | 'connected' | 'unreachable';

interface HealthState {
  state: ConnectionState;
  data: HealthResponse | null;
}

/**
 * Polls backend health. The real-time layer (Milestone 5) replaces polling
 * with a WebSocket; the connection-state vocabulary established here is the
 * same one the live client will use.
 */
export function useHealth(pollIntervalMs = 10_000): HealthState {
  const [health, setHealth] = useState<HealthState>({ state: 'checking', data: null });

  useEffect(() => {
    const controller = new AbortController();

    const check = async (): Promise<void> => {
      try {
        const data = await fetchHealth(controller.signal);
        setHealth({ state: 'connected', data });
      } catch {
        if (!controller.signal.aborted) {
          setHealth({ state: 'unreachable', data: null });
        }
      }
    };

    void check();
    const timer = window.setInterval(() => void check(), pollIntervalMs);

    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [pollIntervalMs]);

  return health;
}
