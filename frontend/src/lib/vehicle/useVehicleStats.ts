/**
 * Live vehicle stats for a driver. **Simulated — this is the file to replace.**
 *
 * Shaped as a subscription rather than a fetch precisely so the swap is a
 * one-file change: `subscribeToVehicleStats` already has the signature a real
 * transport has (start, push repeatedly, return an unsubscribe), so pointing it
 * at the trip WebSocket or a telemetry endpoint means rewriting the body and
 * nothing else. The hook below never learns where the numbers came from.
 *
 * The numbers are a random walk with plausible bounds and coupling — speed and
 * RPM move together, fuel only falls, the odometer only rises. They are not a
 * physics model; `simulator/` is where the real vehicle model lives, and if
 * this page ever needs true telemetry it should read that rather than grow its
 * own second one.
 */
import { useEffect, useState } from 'react';

export interface VehicleStats {
  speedKph: number;
  rpm: number;
  fuelPercent: number;
  engineTempC: number;
  odometerKm: number;
  /** Seconds since the driver's shift began. */
  tripDurationS: number;
}

export type VehicleStatsListener = (stats: VehicleStats) => void;

const TICK_MS = 1000;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** Deterministic-ish seed per driver, so two codes don't show identical numbers. */
function seedFor(driverCode: string): number {
  let hash = 0;
  for (const char of driverCode) {
    hash = (hash * 31 + char.charCodeAt(0)) % 100_000;
  }
  return hash;
}

function initialStats(driverCode: string, shiftStartedAt: string): VehicleStats {
  const seed = seedFor(driverCode);
  return {
    speedKph: 48 + (seed % 20),
    rpm: 1500 + (seed % 400),
    fuelPercent: 40 + (seed % 45),
    engineTempC: 86 + (seed % 6),
    odometerKm: 40_000 + (seed % 60_000),
    tripDurationS: Math.max(0, (Date.now() - new Date(shiftStartedAt).getTime()) / 1000),
  };
}

function step(previous: VehicleStats): VehicleStats {
  const speedKph = clamp(previous.speedKph + (Math.random() - 0.5) * 6, 0, 110);
  return {
    speedKph,
    // Loosely tied to speed rather than independent, so the two panels don't
    // visibly contradict each other (idling at 2,500 rpm, say).
    rpm: clamp(700 + speedKph * 28 + (Math.random() - 0.5) * 150, 650, 3200),
    fuelPercent: clamp(previous.fuelPercent - 0.008, 0, 100),
    engineTempC: clamp(previous.engineTempC + (Math.random() - 0.5) * 0.4, 70, 110),
    odometerKm: previous.odometerKm + speedKph / 3600,
    tripDurationS: previous.tripDurationS + TICK_MS / 1000,
  };
}

/**
 * Push vehicle stats to `listener` roughly once a second until unsubscribed.
 * Returns the unsubscribe function.
 */
export function subscribeToVehicleStats(
  driverCode: string,
  shiftStartedAt: string,
  listener: VehicleStatsListener,
): () => void {
  let current = initialStats(driverCode, shiftStartedAt);
  listener(current);

  const timer = window.setInterval(() => {
    current = step(current);
    listener(current);
  }, TICK_MS);

  return () => window.clearInterval(timer);
}

/** React binding over the subscription above. Null until the first push. */
export function useVehicleStats(
  driverCode: string | null,
  shiftStartedAt: string | null,
): VehicleStats | null {
  const [stats, setStats] = useState<VehicleStats | null>(null);

  useEffect(() => {
    if (!driverCode || !shiftStartedAt) {
      setStats(null);
      return;
    }
    return subscribeToVehicleStats(driverCode, shiftStartedAt, setStats);
  }, [driverCode, shiftStartedAt]);

  return stats;
}
