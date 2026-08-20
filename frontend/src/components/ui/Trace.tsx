const WINDOW_SECONDS = 30;

export type TraceProvenance = 'RULES_ONLY' | 'MODEL_AND_RULES_AGREE' | 'MODEL_ONLY';

interface TraceProps {
  sampleCount: number;
  coverageRatio: number;
  provenance: TraceProvenance;
  className?: string;
}

const PROVENANCE_LABEL: Record<TraceProvenance, string> = {
  RULES_ONLY: 'rules only',
  MODEL_AND_RULES_AGREE: 'model and rules agree',
  MODEL_ONLY: 'model only',
};

/**
 * Which source(s) produced the band, as two source-letter cells rather than
 * an abstract icon: `R` lit means the rules decided it, `M` lit means the
 * model did. `MODEL_AND_RULES_AGREE` lights both, because both independently
 * reached the same band.
 */
function ProvenanceGlyph({ provenance }: { provenance: TraceProvenance }) {
  const rulesLit = provenance !== 'MODEL_ONLY';
  const modelLit = provenance !== 'RULES_ONLY';
  return (
    <span className="ml-1.5 flex items-center gap-px font-mono text-[10px] font-semibold leading-none">
      <span className={rulesLit ? 'text-content-secondary' : 'text-content-muted/40'}>R</span>
      <span className={modelLit ? 'text-content-secondary' : 'text-content-muted/40'}>M</span>
    </span>
  );
}

/**
 * The signature element: one cell per second of the 30-second window a score
 * was computed from, so a score never appears without the evidence it rests
 * on (design plan, "no score without its evidence").
 *
 * The backend only reports aggregate `coverage_ratio` / `sample_count`, not
 * which specific seconds had samples — there is no per-second bitmap to draw.
 * Packing lit cells at one end would assert a timeline the data doesn't
 * support, so the lit count is spread evenly across the strip instead. That
 * keeps the strip honest about quantity without claiming to know *when*
 * within the window the gaps fell.
 *
 * Achromatic by design-system rule 1 (colour only ever means risk): this is a
 * measurement-quality signal, not a risk reading, so it never borrows the
 * band scale.
 */
export function Trace({ sampleCount, coverageRatio, provenance, className = '' }: TraceProps) {
  const lit = Math.max(0, Math.min(WINDOW_SECONDS, Math.round(coverageRatio * WINDOW_SECONDS)));
  const label = `${sampleCount} of ${WINDOW_SECONDS}s window covered · ${PROVENANCE_LABEL[provenance]}`;

  return (
    <div
      className={`inline-flex items-center ${className}`}
      role="img"
      aria-label={label}
      title={label}
    >
      <div className="flex items-end gap-px">
        {Array.from({ length: WINDOW_SECONDS }, (_, i) => {
          const on =
            Math.floor((i * lit) / WINDOW_SECONDS) !== Math.floor(((i - 1) * lit) / WINDOW_SECONDS);
          return (
            <span
              key={i}
              className={`h-3 w-[3px] rounded-[1px] ${on ? 'bg-content-secondary' : 'bg-border-subtle'}`}
            />
          );
        })}
      </div>
      <ProvenanceGlyph provenance={provenance} />
    </div>
  );
}
