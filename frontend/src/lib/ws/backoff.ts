/**
 * Reconnect backoff: capped exponential with full jitter.
 *
 * Full jitter rather than a fixed ladder because the failure this exists for
 * is usually the *server* going away, and every open tab notices at the same
 * instant. A deterministic delay would have them all retry in lockstep and
 * hit the restarting backend as one wave, repeatedly. Randomising the whole
 * interval spreads them out.
 *
 * Pure and clock-free so the policy is testable without a socket.
 */

export interface BackoffOptions {
  /** Delay ceiling before jitter, in ms. */
  baseMs?: number;
  capMs?: number;
}

export const DEFAULT_BASE_MS = 500;
export const DEFAULT_CAP_MS = 15_000;

/**
 * Delay before retry number `attempt` (0-based: 0 is the first retry).
 *
 * `random` is injectable so tests can pin it; it must return [0, 1).
 */
export function nextDelayMs(
  attempt: number,
  { baseMs = DEFAULT_BASE_MS, capMs = DEFAULT_CAP_MS }: BackoffOptions = {},
  random: () => number = Math.random,
): number {
  const bounded = Math.min(capMs, baseMs * 2 ** Math.max(0, attempt));
  return Math.round(random() * bounded);
}

/**
 * How long a socket must stay open before its attempt counter resets.
 *
 * Without this, a server that accepts a connection and immediately drops it
 * would reset the backoff on every cycle and turn the retry loop into a hot
 * one. A connection has to actually survive to count as a success.
 */
export const STABLE_CONNECTION_MS = 3_000;
