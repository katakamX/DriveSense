import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { ObdSummary } from '@/components/obd/ObdSummary';
import type { ObdChunk, ObdRiskBand, ObdRiskOut } from '@/lib/api/obd';

afterEach(cleanup);

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

describe('ObdSummary', () => {
  it('grades a clean session A and labels it RULES_ONLY', () => {
    const chunks = Array.from({ length: 40 }, (_, i) => chunk(i, risk('CALM')));
    render(<ObdSummary chunks={chunks} />);
    expect(screen.getByRole('img', { name: 'Session grade A' })).toBeDefined();
    expect(screen.getByText('RULES_ONLY')).toBeDefined();
    expect(screen.getByText('CALM 100%')).toBeDefined();
  });

  it('surfaces HIGH_RISK as the peak band and shows harsh-braking events', () => {
    const rule = 'harsh_braking_per_min>=2.0';
    const chunks = [
      ...Array.from({ length: 20 }, (_, i) => chunk(i, risk('CALM'))),
      chunk(20, risk('HIGH_RISK', [rule])),
      chunk(21, risk('HIGH_RISK', [rule])),
    ];
    render(<ObdSummary chunks={chunks} />);
    expect(screen.getByRole('img', { name: 'Session grade D' })).toBeDefined();
    expect(screen.getAllByText('HIGH_RISK').length).toBeGreaterThan(0);
    const harshBrakingLabel = screen.getByText('Harsh-braking events');
    const tile = harshBrakingLabel.parentElement;
    expect(tile?.textContent).toContain('1');
  });

  it('handles a replay with no scored chunks without crashing', () => {
    render(<ObdSummary chunks={[chunk(0, null), chunk(1, null)]} />);
    expect(screen.getByRole('img', { name: 'Session grade A' })).toBeDefined();
    expect(screen.getByText('0 of 2 chunks scored', { exact: false })).toBeDefined();
  });
});
