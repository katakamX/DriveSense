import { AlertTriangle, Camera, CameraOff, Eye, EyeOff, UserX, Wind } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { StatTile } from '@/components/ui/StatTile';
import { DriverNotFoundError, lookupDriver, type Driver } from '@/lib/drivers/lookupDriver';
import { useWebcam } from '@/lib/media/useWebcam';
import { useVehicleStats } from '@/lib/vehicle/useVehicleStats';
import { useDriverMonitor, type MonitorConnectionState } from '@/lib/ws/useDriverMonitor';

const CONNECTION_LABEL: Record<MonitorConnectionState, { text: string; dot: string }> = {
  connecting: { text: 'Connecting', dot: 'bg-content-muted' },
  connected: { text: 'Monitoring', dot: 'bg-risk-low' },
  reconnecting: { text: 'Reconnecting', dot: 'bg-risk-moderate' },
  unreachable: { text: 'Disconnected', dot: 'bg-risk-critical' },
};

function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  return `${hours}h ${String(minutes).padStart(2, '0')}m`;
}

function formatRatio(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(3) : '—';
}

interface StatusBadgeProps {
  active: boolean;
  tone: BadgeTone;
  icon: typeof Eye;
  activeLabel: string;
  idleLabel: string;
}

/**
 * Status is never carried by colour alone — each badge states its condition in
 * words and swaps its icon, per the tokens file's accessibility note.
 */
function StatusBadge({ active, tone, icon: Icon, activeLabel, idleLabel }: StatusBadgeProps) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon
        className={`h-3.5 w-3.5 ${active ? 'text-content-primary' : 'text-content-muted'}`}
        aria-hidden="true"
      />
      <Badge tone={active ? tone : 'neutral'}>{active ? activeLabel : idleLabel}</Badge>
    </span>
  );
}

export function DriverMonitor() {
  const [code, setCode] = useState('');
  const [driver, setDriver] = useState<Driver | null>(null);
  const [lookupState, setLookupState] = useState<'idle' | 'pending' | 'error'>('idle');
  const [lookupError, setLookupError] = useState<string | null>(null);

  const webcam = useWebcam();
  const stats = useVehicleStats(driver?.driverCode ?? null, driver?.shiftStartedAt ?? null);
  const { connection, reading, frameError } = useDriverMonitor(
    driver?.driverCode ?? null,
    webcam.stream,
  );

  const videoRef = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    if (videoRef.current && webcam.stream) {
      videoRef.current.srcObject = webcam.stream;
    }
  }, [webcam.stream]);

  const handleSubmit = async (event: FormEvent): Promise<void> => {
    event.preventDefault();
    if (!code.trim()) {
      return;
    }
    setLookupState('pending');
    setLookupError(null);
    try {
      const found = await lookupDriver(code);
      setDriver(found);
      setLookupState('idle');
      // Only ask for the camera once there is a driver to attribute the
      // footage to. A permission prompt before that has nothing to justify it.
      webcam.start();
    } catch (cause) {
      setDriver(null);
      webcam.stop();
      setLookupState('error');
      setLookupError(
        cause instanceof DriverNotFoundError
          ? cause.message
          : 'Driver lookup failed. Try again in a moment.',
      );
    }
  };

  const drowsy = reading?.drowsy ?? false;
  const label = CONNECTION_LABEL[connection];

  return (
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Driver Monitor</h1>
          <p className="mt-1 text-content-secondary">
            {driver ? `${driver.name} · ${driver.vehicle}` : 'Enter a driver code to begin'}
          </p>
        </div>
        {driver && (
          <div className="flex items-center gap-2.5 rounded-lg border border-border-subtle bg-surface-raised px-3 py-1.5">
            <span className={`h-2 w-2 rounded-full ${label.dot}`} aria-hidden="true" />
            <span className="text-sm text-content-primary">{label.text}</span>
          </div>
        )}
      </div>

      <form onSubmit={(event) => void handleSubmit(event)} className="mt-6 flex flex-wrap gap-3">
        <label className="sr-only" htmlFor="driver-code">
          Driver code
        </label>
        <input
          id="driver-code"
          value={code}
          onChange={(event) => setCode(event.target.value)}
          placeholder="Driver code, e.g. DRV-1001"
          autoComplete="off"
          className="min-w-64 flex-1 rounded-lg border border-border-subtle bg-surface-raised px-4 py-2.5 text-content-primary placeholder:text-content-muted focus:border-accent focus:outline-none"
        />
        <button
          type="submit"
          disabled={lookupState === 'pending' || !code.trim()}
          className="rounded-lg bg-accent px-5 py-2.5 font-medium text-surface-base transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {lookupState === 'pending' ? 'Looking up…' : 'Start monitoring'}
        </button>
      </form>

      {lookupError && <p className="mt-3 text-sm text-risk-critical">{lookupError}</p>}

      {!driver && lookupState !== 'error' && (
        <Panel className="mt-6 p-8 text-center">
          <Camera className="mx-auto h-8 w-8 text-content-muted" aria-hidden="true" />
          <p className="mt-3 text-content-secondary">
            No driver selected. Enter a code to load their vehicle stats and start cabin monitoring.
          </p>
        </Panel>
      )}

      {driver && (
        <>
          {drowsy && (
            <div
              role="alert"
              className="mt-6 flex items-center gap-3 rounded-lg border border-risk-critical/40 bg-risk-critical/10 px-5 py-4"
            >
              <AlertTriangle className="h-6 w-6 shrink-0 text-risk-critical" aria-hidden="true" />
              <div>
                <p className="font-semibold text-risk-critical">Drowsiness detected</p>
                <p className="text-sm text-content-secondary">
                  Eyes have been closed continuously past the alert threshold. Advise the driver to
                  stop at the next safe opportunity.
                </p>
              </div>
            </div>
          )}

          <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6">
            <StatTile label="Speed" value={stats ? stats.speedKph.toFixed(0) : '—'} unit="km/h" />
            <StatTile label="RPM" value={stats ? stats.rpm.toFixed(0) : '—'} />
            <StatTile label="Fuel" value={stats ? stats.fuelPercent.toFixed(0) : '—'} unit="%" />
            <StatTile label="Engine" value={stats ? stats.engineTempC.toFixed(0) : '—'} unit="°C" />
            <StatTile
              label="Odometer"
              value={stats ? stats.odometerKm.toFixed(0) : '—'}
              unit="km"
            />
            <StatTile label="Trip" value={stats ? formatDuration(stats.tripDurationS) : '—'} />
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[3fr_2fr]">
            <Panel className="overflow-hidden p-0">
              <div className="flex items-center justify-between border-b border-border-subtle px-5 py-3">
                <span className="text-sm font-medium text-content-secondary">Cabin camera</span>
                <span className="text-xs text-content-muted">
                  {driver.licencePlate} · {driver.driverCode}
                </span>
              </div>

              <div className="relative aspect-video bg-surface-base">
                {webcam.state === 'ready' ? (
                  <video
                    ref={videoRef}
                    autoPlay
                    playsInline
                    muted
                    // Mirrored: a driver glancing at their own feed expects a
                    // mirror, not a rear view. Detection runs on the unmirrored
                    // frame server-side, and EAR/MAR are reflection-invariant
                    // anyway.
                    className="h-full w-full -scale-x-100 object-cover"
                  />
                ) : (
                  <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
                    <CameraOff className="h-8 w-8 text-content-muted" aria-hidden="true" />
                    <p className="text-content-secondary">
                      {webcam.state === 'requesting'
                        ? 'Waiting for camera permission…'
                        : (webcam.error ?? 'Camera not started.')}
                    </p>
                    {(webcam.state === 'denied' || webcam.state === 'error') && (
                      <button
                        type="button"
                        onClick={webcam.start}
                        className="rounded-md border border-border-strong px-3 py-1.5 text-sm text-content-primary hover:bg-surface-overlay"
                      >
                        Retry camera
                      </button>
                    )}
                  </div>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2 border-t border-border-subtle px-5 py-3">
                <StatusBadge
                  active={reading?.face_detected ?? false}
                  tone="low"
                  icon={Eye}
                  activeLabel="Face detected"
                  idleLabel="No face"
                />
                <StatusBadge
                  active={reading?.eyes_closed ?? false}
                  tone="moderate"
                  icon={EyeOff}
                  activeLabel="Eyes closed"
                  idleLabel="Eyes open"
                />
                <StatusBadge
                  active={reading?.yawning ?? false}
                  tone="high"
                  icon={Wind}
                  activeLabel="Yawning"
                  idleLabel="No yawn"
                />
                <StatusBadge
                  active={drowsy}
                  tone="critical"
                  icon={AlertTriangle}
                  activeLabel="Drowsy"
                  idleLabel="Alert"
                />
                {reading?.not_visible && (
                  <StatusBadge
                    active
                    tone="high"
                    icon={UserX}
                    activeLabel="Driver not visible"
                    idleLabel=""
                  />
                )}
              </div>
            </Panel>

            <Panel className="overflow-hidden p-0">
              <div className="border-b border-border-subtle px-5 py-3 text-sm font-medium text-content-secondary">
                Detection signals
              </div>
              <dl className="divide-y divide-border-subtle">
                <div className="flex items-center justify-between px-5 py-3">
                  <dt className="text-sm text-content-secondary">Eye aspect ratio</dt>
                  <dd className="tabular text-content-primary">{formatRatio(reading?.ear)}</dd>
                </div>
                <div className="flex items-center justify-between px-5 py-3">
                  <dt className="text-sm text-content-secondary">Mouth aspect ratio</dt>
                  <dd className="tabular text-content-primary">{formatRatio(reading?.mar)}</dd>
                </div>
                <div className="flex items-center justify-between px-5 py-3">
                  <dt className="text-sm text-content-secondary">Last frame</dt>
                  <dd className="tabular text-sm text-content-secondary">
                    {reading ? new Date(reading.timestamp).toLocaleTimeString() : '—'}
                  </dd>
                </div>
              </dl>

              <p className="border-t border-border-subtle px-5 py-3 text-xs leading-relaxed text-content-muted">
                Thresholds are fixed, not calibrated to this driver: eye aspect ratio varies with
                eye shape, glasses and camera angle. These flags report a threshold crossing
                sustained over time, not a measurement of alertness, and this is not a safety
                device.
              </p>

              {frameError && (
                <p className="border-t border-border-subtle px-5 py-3 text-xs text-risk-moderate">
                  Last frame was rejected: {frameError}
                </p>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}
