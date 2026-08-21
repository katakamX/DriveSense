import { describe, expect, it } from 'vitest';

import type { ObdChunk, ObdRiskBand, ObdRiskOut } from '@/lib/api/obd';
import { summarizeObdReplay } from '@/lib/obd/grade';

function risk(band: ObdRiskBand, matchedRules: string[] = []): ObdRiskOut {
  return {
    sample_count: 30,
    coverage_ratio: 1,
    score: 0,
    band,
    provenance: 'RULES_ONLY',
    gated: false,
    matched_rules: matchedRules,
  };
}

function chunk(t: number, riskOut: ObdRiskOut | null): ObdChunk {
  return { t, speed_kmh: 0, rpm: 0, gear: 0, throttle_pct: 0, brake_pct: 0, risk: riskOut };
}

describe('summarizeObdReplay', () => {
  it('reports zeros and a null peak band when nothing was ever scored', () => {
    const summary = summarizeObdReplay([chunk(0, null), chunk(1, null)]);
    expect(summary.scoredChunkCount).toBe(0);
    expect(summary.totalChunkCount).toBe(2);
    expect(summary.peakBand).toBeNull();
    expect(summary.bandDistribution).toEqual({ CALM: 0, NORMAL: 0, AGGRESSIVE: 0, HIGH_RISK: 0 });
    expect(summary.grade).toBe('A');
  });

  it('ignores unscored warm-up chunks when computing distribution', () => {
    const chunks = [chunk(0, null), chunk(1, null), chunk(2, risk('CALM')), chunk(3, risk('CALM'))];
    const summary = summarizeObdReplay(chunks);
    expect(summary.scoredChunkCount).toBe(2);
    expect(summary.totalChunkCount).toBe(4);
    expect(summary.bandDistribution.CALM).toBe(1);
  });

  it('computes band distribution as a fraction of scored chunks', () => {
    const chunks = [
      chunk(0, risk('CALM')),
      chunk(1, risk('CALM')),
      chunk(2, risk('NORMAL')),
      chunk(3, risk('AGGRESSIVE')),
    ];
    const summary = summarizeObdReplay(chunks);
    expect(summary.bandDistribution).toEqual({
      CALM: 0.5,
      NORMAL: 0.25,
      AGGRESSIVE: 0.25,
      HIGH_RISK: 0,
    });
  });

  it('reports the most severe band reached as the peak, even if brief', () => {
    const chunks = [
      chunk(0, risk('CALM')),
      chunk(1, risk('CALM')),
      chunk(2, risk('CALM')),
      chunk(3, risk('HIGH_RISK')),
      chunk(4, risk('CALM')),
    ];
    expect(summarizeObdReplay(chunks).peakBand).toBe('HIGH_RISK');
  });

  it('counts one event per contiguous matched-rule streak, not per matched chunk', () => {
    const rule = 'harsh_braking_per_min>=2.0';
    // One ~3-chunk streak, a gap, then another ~2-chunk streak: 2 events, not 5 matched chunks.
    const chunks = [
      chunk(0, risk('AGGRESSIVE', [rule])),
      chunk(1, risk('AGGRESSIVE', [rule])),
      chunk(2, risk('AGGRESSIVE', [rule])),
      chunk(3, risk('NORMAL')),
      chunk(4, risk('NORMAL')),
      chunk(5, risk('AGGRESSIVE', [rule])),
      chunk(6, risk('AGGRESSIVE', [rule])),
    ];
    const summary = summarizeObdReplay(chunks);
    expect(summary.harshBraking.count).toBe(2);
    expect(summary.harshBraking.activeShare).toBeCloseTo(5 / 7);
  });

  it('keeps harsh-braking and rapid-accel counts independent', () => {
    const brakeRule = 'harsh_braking_per_min>=2.0';
    const accelRule = 'accel_max>=1.5';
    const chunks = [
      chunk(0, risk('AGGRESSIVE', [brakeRule])),
      chunk(1, risk('AGGRESSIVE', [accelRule])),
      chunk(2, risk('AGGRESSIVE', [brakeRule, accelRule])),
    ];
    const summary = summarizeObdReplay(chunks);
    // Brake-rule matches at chunks 0 and 2 are not contiguous (chunk 1 breaks the streak): 2 events.
    expect(summary.harshBraking.count).toBe(2);
    // Accel-rule matches at chunks 1 and 2 are contiguous: 1 event.
    expect(summary.rapidAccel.count).toBe(1);
  });

  it('grades a clean session A', () => {
    const chunks = Array.from({ length: 40 }, (_, i) => chunk(i, risk('CALM')));
    expect(summarizeObdReplay(chunks).grade).toBe('A');
  });

  it('grades a session with light aggressive time B', () => {
    const chunks = [
      ...Array.from({ length: 95 }, (_, i) => chunk(i, risk('CALM'))),
      ...Array.from({ length: 5 }, (_, i) => chunk(95 + i, risk('AGGRESSIVE'))),
    ];
    expect(summarizeObdReplay(chunks).grade).toBe('B');
  });

  it('grades a session with substantial aggressive time C', () => {
    const chunks = [
      ...Array.from({ length: 85 }, (_, i) => chunk(i, risk('CALM'))),
      ...Array.from({ length: 15 }, (_, i) => chunk(85 + i, risk('AGGRESSIVE'))),
    ];
    expect(summarizeObdReplay(chunks).grade).toBe('C');
  });

  it('caps the grade at D as soon as any HIGH_RISK time appears', () => {
    const chunks = [
      ...Array.from({ length: 99 }, (_, i) => chunk(i, risk('CALM'))),
      chunk(99, risk('HIGH_RISK')),
    ];
    expect(summarizeObdReplay(chunks).grade).toBe('D');
  });

  it('grades a session dominated by HIGH_RISK time F', () => {
    const chunks = [
      ...Array.from({ length: 70 }, (_, i) => chunk(i, risk('CALM'))),
      ...Array.from({ length: 30 }, (_, i) => chunk(70 + i, risk('HIGH_RISK'))),
    ];
    expect(summarizeObdReplay(chunks).grade).toBe('F');
  });
});
