/**
 * Post-drive summary derived entirely from a session's own `ObdRiskOut`
 * chunks — never from the CSV's precomputed columns (Driver_Aggression_pct
 * etc.), which stay unused per STEP4_FINDINGS.md's decision (b), same as
 * `app.core.risk.rules.evaluate_obd` on the backend. Every band here came
 * out of that RULES_ONLY engine; nothing here is a model score.
 */
import type { ObdChunk, ObdRiskBand } from '@/lib/api/obd';

export type ObdGrade = 'A' | 'B' | 'C' | 'D' | 'F';

/** `app.core.risk.rules.evaluate_obd`'s AGGRESSIVE rule IDs this summary calls out by name. */
const HARSH_BRAKING_RULE = 'harsh_braking_per_min>=2.0';
/**
 * OBD windows have no independent "rapid acceleration" rule — `rapid_accel_per_min`
 * is derivable but `evaluate_obd` never thresholds on it directly (see `OBD_RULE_IDS`
 * in `backend/app/core/risk/rules.py`). `accel_max>=1.5` is the rule that actually
 * fires on hard acceleration in the OBD rule set, so it stands in as this summary's
 * "rapid acceleration" count rather than reporting a rule that can never appear.
 */
const RAPID_ACCEL_RULE = 'accel_max>=1.5';

/** CALM is least severe, HIGH_RISK most — mirrors `RiskBand`'s severity axis in `backend/app/core/risk/schema.py`. */
const BAND_SEVERITY: readonly ObdRiskBand[] = ['CALM', 'NORMAL', 'AGGRESSIVE', 'HIGH_RISK'];

export type ObdBandDistribution = Record<ObdRiskBand, number>;

export interface ObdRuleEventSummary {
  /** Contiguous matched-rule streaks across scored chunks — see `countRuleEvents` for why this is an event count and not a frame count. */
  count: number;
  /** Fraction of scored chunks where the rule was matched, independent of streak boundaries. */
  activeShare: number;
}

export interface ObdReplaySummary {
  scoredChunkCount: number;
  totalChunkCount: number;
  /** Fraction of *scored* chunks in each band; sums to 1 when scoredChunkCount > 0, else all 0. */
  bandDistribution: ObdBandDistribution;
  /** Worst band reached this session, or null if nothing was ever scored. */
  peakBand: ObdRiskBand | null;
  /** AGGRESSIVE + HIGH_RISK share — "time in the danger zone". */
  dangerZoneShare: number;
  harshBraking: ObdRuleEventSummary;
  rapidAccel: ObdRuleEventSummary;
  grade: ObdGrade;
}

/**
 * One window's risk (`RiskOut`) persists across roughly 30 consecutive
 * chunks — the trailing-window span (`WINDOW_SPAN_S` on the backend) — so a
 * single physical brake application shows up as one long streak of matched
 * chunks, not one chunk. Counting streaks, not matched chunks, is what makes
 * "count" mean "number of events" instead of "seconds the rule happened to
 * be true". Two real events close enough together to stay inside the same
 * 30s window the whole time will undercount as one streak; there is no way
 * to recover per-event timing from an aggregate rule match, so this is
 * reported as an approximation, not exact telemetry.
 */
function countRuleEvents(scoredChunks: ObdChunk[], ruleId: string): ObdRuleEventSummary {
  let count = 0;
  let activeCount = 0;
  let previousActive = false;
  for (const chunk of scoredChunks) {
    const active = chunk.risk!.matched_rules.includes(ruleId);
    if (active) {
      activeCount += 1;
      if (!previousActive) count += 1;
    }
    previousActive = active;
  }
  return {
    count,
    activeShare: scoredChunks.length > 0 ? activeCount / scoredChunks.length : 0,
  };
}

function peakBand(distribution: ObdBandDistribution): ObdRiskBand | null {
  for (let i = BAND_SEVERITY.length - 1; i >= 0; i -= 1) {
    const band = BAND_SEVERITY[i];
    if (band && distribution[band] > 0) return band;
  }
  return null;
}

/**
 * The grade is driven by how much of the session landed in the two most
 * severe bands, with HIGH_RISK weighted far above AGGRESSIVE since it is the
 * band the rules engine reserves for its single most dangerous rule
 * (`speeding_time_ratio>=0.5 and accel_min<=-2.0`, unchanged from `evaluate`).
 * Any HIGH_RISK time at all caps the grade at D or worse — a rules engine
 * that reports even one HIGH_RISK window is not describing an A- or
 * B-quality drive. Below that, AGGRESSIVE time (plus what HIGH_RISK time
 * remains under the F cutoff) is the "danger zone" share that steps the
 * grade down from A.
 *
 * This mapping is a real design choice, not a derived constant — the
 * thresholds below are picked to match the user-facing framing "mostly
 * CALM/NORMAL -> A, meaningful HIGH_RISK time -> lower grade" and can be
 * retuned without touching anything upstream of `bandDistribution`.
 */
function gradeFor(distribution: ObdBandDistribution): ObdGrade {
  const highRisk = distribution.HIGH_RISK;
  const dangerZone = distribution.AGGRESSIVE + distribution.HIGH_RISK;

  if (highRisk > 0.2) return 'F';
  if (highRisk > 0) return 'D';
  if (dangerZone > 0.3) return 'D';
  if (dangerZone > 0.1) return 'C';
  if (dangerZone > 0.02) return 'B';
  return 'A';
}

export function summarizeObdReplay(chunks: ObdChunk[]): ObdReplaySummary {
  const scored = chunks.filter((chunk) => chunk.risk !== null);

  const counts: ObdBandDistribution = { CALM: 0, NORMAL: 0, AGGRESSIVE: 0, HIGH_RISK: 0 };
  for (const chunk of scored) counts[chunk.risk!.band] += 1;

  const bandDistribution: ObdBandDistribution = { CALM: 0, NORMAL: 0, AGGRESSIVE: 0, HIGH_RISK: 0 };
  if (scored.length > 0) {
    for (const band of BAND_SEVERITY) {
      bandDistribution[band] = counts[band] / scored.length;
    }
  }

  return {
    scoredChunkCount: scored.length,
    totalChunkCount: chunks.length,
    bandDistribution,
    peakBand: peakBand(bandDistribution),
    dangerZoneShare: bandDistribution.AGGRESSIVE + bandDistribution.HIGH_RISK,
    harshBraking: countRuleEvents(scored, HARSH_BRAKING_RULE),
    rapidAccel: countRuleEvents(scored, RAPID_ACCEL_RULE),
    grade: gradeFor(bandDistribution),
  };
}
