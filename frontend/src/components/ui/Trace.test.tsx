import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';

import { Trace, type TraceProvenance } from '@/components/ui/Trace';

afterEach(cleanup);

const WINDOW_SECONDS = 30;

/**
 * The strip is the product's claim about how much evidence a score rests on,
 * so the count of lit cells has to equal the coverage it is reporting — an
 * off-by-one here would silently overstate or understate the evidence rather
 * than fail loudly.
 */
function litCellCount(container: HTMLElement): number {
  const cells = container.querySelectorAll('span[class*="w-[3px]"]');
  return Array.from(cells).filter((c) => c.className.includes('bg-content-secondary')).length;
}

function cellCount(container: HTMLElement): number {
  return container.querySelectorAll('span[class*="w-[3px]"]').length;
}

describe('Trace', () => {
  it('always draws exactly one cell per second of the window', () => {
    const { container } = render(
      <Trace sampleCount={12} coverageRatio={0.4} provenance="RULES_ONLY" />,
    );
    expect(cellCount(container)).toBe(WINDOW_SECONDS);
  });

  it('lights a cell count matching the coverage ratio, for every whole-second ratio', () => {
    for (let covered = 0; covered <= WINDOW_SECONDS; covered += 1) {
      const { container } = render(
        <Trace
          sampleCount={covered}
          coverageRatio={covered / WINDOW_SECONDS}
          provenance="RULES_ONLY"
        />,
      );
      expect(litCellCount(container)).toBe(covered);
      cleanup();
    }
  });

  it('draws an empty strip at zero coverage and a full one at total coverage', () => {
    const { container: empty } = render(
      <Trace sampleCount={0} coverageRatio={0} provenance="RULES_ONLY" />,
    );
    expect(litCellCount(empty)).toBe(0);
    cleanup();

    const { container: full } = render(
      <Trace sampleCount={30} coverageRatio={1} provenance="RULES_ONLY" />,
    );
    expect(litCellCount(full)).toBe(WINDOW_SECONDS);
  });

  /** Coverage arrives from the API as a float; a bad one must not overdraw. */
  it('clamps out-of-range coverage instead of drawing past the strip', () => {
    const { container: under } = render(
      <Trace sampleCount={0} coverageRatio={-0.5} provenance="RULES_ONLY" />,
    );
    expect(litCellCount(under)).toBe(0);
    expect(cellCount(under)).toBe(WINDOW_SECONDS);
    cleanup();

    const { container: over } = render(
      <Trace sampleCount={99} coverageRatio={1.7} provenance="RULES_ONLY" />,
    );
    expect(litCellCount(over)).toBe(WINDOW_SECONDS);
    expect(cellCount(over)).toBe(WINDOW_SECONDS);
  });

  it.each<[TraceProvenance, string]>([
    ['RULES_ONLY', 'rules only'],
    ['MODEL_AND_RULES_AGREE', 'model and rules agree'],
    ['MODEL_ONLY', 'model only'],
  ])('states %s in an accessible label rather than by glyph alone', (provenance, expected) => {
    render(<Trace sampleCount={24} coverageRatio={0.8} provenance={provenance} />);
    expect(
      screen.getByRole('img', { name: `24 of 30s window covered · ${expected}` }),
    ).toBeDefined();
  });

  it('lights R for rules, M for model, and both when they agree', () => {
    const dim = (el: Element | undefined) => el?.className.includes('text-content-muted/40');

    const { container: rulesOnly } = render(
      <Trace sampleCount={30} coverageRatio={1} provenance="RULES_ONLY" />,
    );
    let [r, m] = Array.from(rulesOnly.querySelectorAll('span[class*="text-content"]')).filter((e) =>
      ['R', 'M'].includes(e.textContent ?? ''),
    );
    expect(dim(r)).toBe(false);
    expect(dim(m)).toBe(true);
    cleanup();

    const { container: modelOnly } = render(
      <Trace sampleCount={30} coverageRatio={1} provenance="MODEL_ONLY" />,
    );
    [r, m] = Array.from(modelOnly.querySelectorAll('span[class*="text-content"]')).filter((e) =>
      ['R', 'M'].includes(e.textContent ?? ''),
    );
    expect(dim(r)).toBe(true);
    expect(dim(m)).toBe(false);
    cleanup();

    const { container: agree } = render(
      <Trace sampleCount={30} coverageRatio={1} provenance="MODEL_AND_RULES_AGREE" />,
    );
    [r, m] = Array.from(agree.querySelectorAll('span[class*="text-content"]')).filter((e) =>
      ['R', 'M'].includes(e.textContent ?? ''),
    );
    expect(dim(r)).toBe(false);
    expect(dim(m)).toBe(false);
  });
});
