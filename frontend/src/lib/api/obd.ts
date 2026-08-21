/** Typed client for the staff OBD CSV replay endpoint (`POST /obd/analyze`). */

export type ObdRiskBand = 'CALM' | 'NORMAL' | 'AGGRESSIVE' | 'HIGH_RISK';
export type ObdProvenance = 'RULES_ONLY' | 'MODEL_AND_RULES_AGREE' | 'MODEL_ONLY';

/**
 * The fields an OBD replay view can act on, mirroring `RiskOut` in
 * `backend/app/schemas/risk.py`. Every OBD-sourced assessment is
 * `provenance: 'RULES_ONLY'` by construction (see `evaluate_obd` in
 * `backend/app/core/risk/rules.py`) — there is no model compatible with
 * OBD-native features.
 */
export interface ObdRiskOut {
  sample_count: number;
  coverage_ratio: number;
  score: number;
  band: ObdRiskBand;
  provenance: ObdProvenance;
  gated: boolean;
  matched_rules: string[];
}

export interface ObdChunk {
  t: number;
  speed_kmh: number;
  rpm: number;
  gear: number;
  throttle_pct: number;
  brake_pct: number;
  risk: ObdRiskOut | null;
}

export interface ObdAnalysis {
  row_count: number;
  duration_s: number;
  chunk_interval_s: number;
  chunks: ObdChunk[];
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

async function failure(response: Response): Promise<Error> {
  const detail = await response
    .json()
    .then((data: { detail?: string }) => data.detail)
    .catch(() => undefined);
  return new Error(detail ?? `Request failed with status ${response.status}`);
}

export async function analyzeObdCsv(file: File, signal?: AbortSignal): Promise<ObdAnalysis> {
  const body = new FormData();
  body.append('file', file);
  const response = await fetch(`${API_BASE}/obd/analyze`, {
    method: 'POST',
    credentials: 'include',
    body,
    signal,
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as ObdAnalysis;
}
