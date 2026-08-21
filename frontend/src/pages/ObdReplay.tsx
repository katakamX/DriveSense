import { useEffect, useRef, useState } from 'react';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { StatTile } from '@/components/ui/StatTile';
import { Trace } from '@/components/ui/Trace';
import { analyzeObdCsv, type ObdAnalysis, type ObdRiskBand } from '@/lib/api/obd';

const RISK_TONE: Record<ObdRiskBand, BadgeTone> = {
  CALM: 'low',
  NORMAL: 'neutral',
  AGGRESSIVE: 'high',
  HIGH_RISK: 'critical',
};

/** Upload a CSV, get the whole replay back in one response (see `app.api.v1.obd`). */
function UploadForm({
  busy,
  error,
  onUpload,
}: {
  busy: boolean;
  error: string | null;
  onUpload: (file: File) => void;
}) {
  return (
    <Panel className="p-6">
      <h2 className="text-lg font-semibold text-content-primary">Upload an OBD2 CSV export</h2>
      <p className="mt-1 text-sm text-content-secondary">
        Parsed and scored with the same OBD-native rules used elsewhere in this app — see{' '}
        <span className="font-mono text-xs">app.core.obd</span>. Nothing is persisted.
      </p>
      <input
        type="file"
        accept=".csv,text/csv"
        disabled={busy}
        aria-label="OBD CSV file"
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onUpload(file);
        }}
        className="mt-4 block text-sm text-content-secondary file:mr-3 file:rounded-md file:border-0 file:bg-surface-overlay file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-content-primary"
      />
      {busy && <p className="mt-3 text-sm text-content-muted">Analyzing…</p>}
      {error && <p className="mt-3 text-sm text-risk-critical">{error}</p>}
    </Panel>
  );
}

/** Auto-plays through pre-fetched chunks at `chunk_interval_s` cadence; also steppable by hand. */
function usePlayer(chunkCount: number, chunkIntervalS: number) {
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(true);
  const atEnd = chunkCount > 0 && index >= chunkCount - 1;

  useEffect(() => {
    if (!playing || atEnd) return;
    const id = setInterval(() => {
      setIndex((i) => Math.min(i + 1, chunkCount - 1));
    }, chunkIntervalS * 1000);
    return () => clearInterval(id);
  }, [playing, atEnd, chunkCount, chunkIntervalS]);

  return { index, setIndex, playing, setPlaying, atEnd };
}

function ChunkPlayer({ analysis }: { analysis: ObdAnalysis }) {
  const { chunks, chunk_interval_s: chunkIntervalS } = analysis;
  const { index, setIndex, playing, setPlaying, atEnd } = usePlayer(chunks.length, chunkIntervalS);
  const chunk = chunks[index];
  if (!chunk) return null;
  const risk = chunk.risk;

  return (
    <div className="mt-6">
      <div className="flex items-center justify-between">
        <p className="text-sm text-content-secondary">
          t = {chunk.t.toFixed(0)}s / {analysis.duration_s.toFixed(0)}s · chunk {index + 1} of{' '}
          {chunks.length}
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setIndex((i) => Math.max(0, i - 1))}
            disabled={index === 0}
            className="rounded-md border border-border-subtle px-2.5 py-1 text-sm text-content-secondary disabled:opacity-40"
          >
            ◀
          </button>
          <button
            type="button"
            onClick={() => setPlaying((p) => !p)}
            disabled={atEnd}
            className="rounded-md border border-border-subtle px-3 py-1 text-sm text-content-primary disabled:opacity-40"
          >
            {playing && !atEnd ? 'Pause' : 'Play'}
          </button>
          <button
            type="button"
            onClick={() => setIndex((i) => Math.min(chunks.length - 1, i + 1))}
            disabled={atEnd}
            className="rounded-md border border-border-subtle px-2.5 py-1 text-sm text-content-secondary disabled:opacity-40"
          >
            ▶
          </button>
        </div>
      </div>

      {risk ? (
        <Panel className="mt-4 flex flex-wrap items-center justify-between gap-3 px-5 py-4">
          <div className="flex items-center gap-3">
            <Badge tone={RISK_TONE[risk.band]}>{risk.band}</Badge>
            <span className="font-display tabular-nums text-2xl font-semibold tracking-display text-content-primary">
              {risk.score.toFixed(1)}
            </span>
            <span className="text-sm text-content-muted">risk score</span>
          </div>
          <Trace
            sampleCount={risk.sample_count}
            coverageRatio={risk.coverage_ratio}
            provenance={risk.provenance}
          />
        </Panel>
      ) : (
        <Panel className="mt-4 px-5 py-4 text-sm text-content-muted">
          Not enough of the recording has played yet to assess a window.
        </Panel>
      )}

      <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-5">
        <StatTile label="Speed" value={chunk.speed_kmh.toFixed(1)} unit="km/h" />
        <StatTile label="RPM" value={chunk.rpm.toFixed(0)} />
        <StatTile label="Gear" value={String(chunk.gear)} />
        <StatTile label="Throttle" value={chunk.throttle_pct.toFixed(0)} unit="%" />
        <StatTile label="Brake" value={chunk.brake_pct.toFixed(0)} unit="%" />
      </div>

      {atEnd && (
        <p className="mt-4 text-center text-sm text-content-muted" aria-live="polite">
          …
        </p>
      )}
    </div>
  );
}

export function ObdReplay() {
  const [analysis, setAnalysis] = useState<ObdAnalysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  function handleUpload(file: File) {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setBusy(true);
    setError(null);
    setAnalysis(null);
    analyzeObdCsv(file, controller.signal)
      .then(setAnalysis)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Could not analyze file');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
  }

  return (
    <div>
      <h1 className="text-2xl font-semibold">OBD Replay</h1>
      <p className="mt-1 text-content-secondary">
        Upload an OBD2 CSV export and replay it as a chunked, rules-only risk assessment.
      </p>

      <div className="mt-6">
        <UploadForm busy={busy} error={error} onUpload={handleUpload} />
      </div>

      {analysis && <ChunkPlayer analysis={analysis} />}
    </div>
  );
}
