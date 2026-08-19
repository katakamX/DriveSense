/** Typed client for a single trip's detail sub-resources (M12 page 2).
 *
 * Gating on the backend allows either staff or the trip's own driver, so
 * every request here needs `credentials: 'include'` — the driver case has
 * no separate staff session to fall back on.
 */

export interface RiskWindow {
  id: number;
  window_start: string;
  window_end: string;
  sample_count: number;
  coverage_ratio: number;
  score: number;
  band: string;
  confidence: number;
  provenance: string;
  model_available: boolean;
  gated: boolean;
  rule_band: string;
  matched_rules: string[];
  model_band: string | null;
  model_score: number | null;
  risk_engine_version: string;
  model_version: string | null;
}

export interface TripEvent {
  id: number;
  trip_id: string;
  event_type: string;
  occurred_at: string;
  measured_value: number;
  threshold_value: number;
}

export interface TelemetryPoint {
  id: number;
  recorded_at: string;
  speed_kph: number;
  accel_ms2: number;
  lateral_accel_ms2: number;
  lat: number | null;
  lon: number | null;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

async function failure(response: Response): Promise<Error> {
  const detail = await response
    .json()
    .then((data: { detail?: string }) => data.detail)
    .catch(() => undefined);
  return new Error(detail ?? `Request failed with status ${response.status}`);
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: 'include', signal });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export function fetchRiskWindows(tripId: string, signal?: AbortSignal): Promise<RiskWindow[]> {
  return getJson(`/trips/${tripId}/risk-windows`, signal);
}

export function fetchTripEvents(tripId: string, signal?: AbortSignal): Promise<TripEvent[]> {
  return getJson(`/trips/${tripId}/events`, signal);
}

export function fetchTripTelemetry(
  tripId: string,
  signal?: AbortSignal,
): Promise<TelemetryPoint[]> {
  return getJson(`/trips/${tripId}/telemetry`, signal);
}
