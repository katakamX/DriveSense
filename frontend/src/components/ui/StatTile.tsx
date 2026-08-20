interface StatTileProps {
  label: string;
  value: string;
  unit?: string;
}

export function StatTile({ label, value, unit }: StatTileProps) {
  return (
    <div className="rounded border border-border-subtle bg-surface-raised p-4">
      <div className="text-xs uppercase tracking-label text-content-muted">{label}</div>
      <div className="tabular mt-1 text-2xl font-semibold text-content-primary">
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-content-secondary">{unit}</span>}
      </div>
    </div>
  );
}
