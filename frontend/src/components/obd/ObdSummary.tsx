import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { StatTile } from '@/components/ui/StatTile';
import type { ObdChunk, ObdRiskBand } from '@/lib/api/obd';
import { summarizeObdReplay, type ObdGrade } from '@/lib/obd/grade';

/** Mirrors the live drive's own band→tone mapping (CALM=low, NORMAL=neutral, AGGRESSIVE=high, HIGH_RISK=critical), extended one tier for the C grade in between. */
const GRADE_TONE: Record<ObdGrade, BadgeTone> = {
  A: 'low',
  B: 'neutral',
  C: 'moderate',
  D: 'high',
  F: 'critical',
};

const BAND_TONE: Record<ObdRiskBand, BadgeTone> = {
  CALM: 'low',
  NORMAL: 'neutral',
  AGGRESSIVE: 'high',
  HIGH_RISK: 'critical',
};

const BAND_BAR_CLASS: Record<ObdRiskBand, string> = {
  CALM: 'bg-risk-low',
  NORMAL: 'bg-content-muted',
  AGGRESSIVE: 'bg-risk-high',
  HIGH_RISK: 'bg-risk-critical',
};

const BAND_ORDER: readonly ObdRiskBand[] = ['CALM', 'NORMAL', 'AGGRESSIVE', 'HIGH_RISK'];

function pct(fraction: number): string {
  return `${Math.round(fraction * 100)}%`;
}

/**
 * The post-drive report shown once playback reaches the last chunk. Every
 * number here comes from `summarizeObdReplay`, which reads nothing but this
 * session's own `ObdRiskOut` chunks — the CSV's precomputed
 * Driver_Aggression_pct / Total_Vehicle_Stress_pct columns are never read
 * (see STEP4_FINDINGS.md decision (b)). The RULES_ONLY badge below is not
 * decoration: every OBD-sourced assessment really is rules-only by
 * construction (`evaluate_obd` has no compatible model), so this report
 * carries no more authority than that.
 */
export function ObdSummary({ chunks }: { chunks: ObdChunk[] }) {
  const summary = summarizeObdReplay(chunks);

  return (
    <Panel className="mt-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-content-primary">Session summary</h2>
          <p className="mt-1 text-sm text-content-secondary">
            Derived from this session's own rule-based risk assessments —{' '}
            <Badge tone="neutral">RULES_ONLY</Badge>. The file's precomputed aggression/stress
            columns are not used.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`flex h-16 w-16 items-center justify-center rounded-full border-2 font-display text-3xl font-semibold ${
              {
                low: 'border-risk-low/40 text-risk-low',
                neutral: 'border-border-subtle text-content-secondary',
                moderate: 'border-risk-moderate/40 text-risk-moderate',
                high: 'border-risk-high/40 text-risk-high',
                critical: 'border-risk-critical/40 text-risk-critical',
              }[GRADE_TONE[summary.grade]]
            }`}
            role="img"
            aria-label={`Session grade ${summary.grade}`}
          >
            {summary.grade}
          </span>
          <div className="text-sm text-content-secondary">
            <div>
              Peak band:{' '}
              {summary.peakBand ? (
                <Badge tone={BAND_TONE[summary.peakBand]}>{summary.peakBand}</Badge>
              ) : (
                <span className="text-content-muted">none scored</span>
              )}
            </div>
            <div className="mt-1">Time in danger zone: {pct(summary.dangerZoneShare)}</div>
          </div>
        </div>
      </div>

      <div className="mt-5">
        <p className="text-xs uppercase tracking-label text-content-muted">
          Band distribution · {summary.scoredChunkCount} of {summary.totalChunkCount} chunks scored
        </p>
        <div className="mt-2 flex h-3 overflow-hidden rounded-sm border border-border-subtle">
          {summary.scoredChunkCount === 0 ? (
            <div className="h-full w-full bg-surface-overlay" />
          ) : (
            BAND_ORDER.map((band) => {
              const share = summary.bandDistribution[band];
              if (share <= 0) return null;
              return (
                <div
                  key={band}
                  className={BAND_BAR_CLASS[band]}
                  style={{ width: `${share * 100}%` }}
                  title={`${band} · ${pct(share)}`}
                />
              );
            })
          )}
        </div>
        <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-content-secondary">
          {BAND_ORDER.map((band) => (
            <span key={band} className="flex items-center gap-1.5">
              <span className={`h-2 w-2 rounded-full ${BAND_BAR_CLASS[band]}`} aria-hidden="true" />
              {band} {pct(summary.bandDistribution[band])}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatTile label="Peak band" value={summary.peakBand ?? '—'} />
        <StatTile label="Danger-zone time" value={pct(summary.dangerZoneShare)} />
        <StatTile label="Harsh-braking events" value={String(summary.harshBraking.count)} />
        <StatTile label="Rapid-accel events" value={String(summary.rapidAccel.count)} />
      </div>
    </Panel>
  );
}
