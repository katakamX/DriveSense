/**
 * Streams downscaled camera frames to the backend and exposes its verdict.
 *
 * Envelope matches `backend/app/schemas/monitor.py`: `{frame}` up,
 * `{type: 'reading' | 'error', ...}` down, one response per frame.
 *
 * ## Capture is driven by the socket, not by a timer alone
 *
 * A naive `setInterval` that posts a frame every 200 ms will, on a slow
 * connection, queue frames faster than the server can answer — and the socket
 * buffer is unbounded, so the driver would be looking at a verdict that is
 * several seconds stale with no indication of it. This hook sends only when
 * the previous frame has been answered (`awaitingReply`), which makes the
 * effective rate degrade to whatever the round trip allows instead of
 * accumulating a backlog. That is ADR 0001's latest-value-wins policy applied
 * on the client side.
 *
 * ## Reconnect
 *
 * Capped exponential backoff with full jitter (`./backoff`). Close code 4400
 * is terminal — the server rejects the driver code itself, and retrying will
 * fail identically forever. A clean 1000 from our own teardown is not retried
 * either. Anything else is.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

import { STABLE_CONNECTION_MS, nextDelayMs } from '@/lib/ws/backoff';
import { buildWsUrl } from '@/lib/ws/url';

export type MonitorConnectionState = 'connecting' | 'connected' | 'reconnecting' | 'unreachable';

export interface MonitorReading {
  type: 'reading';
  timestamp: string;
  driver_code: string;
  face_detected: boolean;
  not_visible: boolean;
  ear: number | null;
  mar: number | null;
  eyes_closed: boolean;
  drowsy: boolean;
  yawning: boolean;
}

interface MonitorErrorMessage {
  type: 'error';
  timestamp: string;
  driver_code: string;
  detail: string;
}

type MonitorMessage = MonitorReading | MonitorErrorMessage;

export interface DriverMonitorState {
  connection: MonitorConnectionState;
  reading: MonitorReading | null;
  /** Last per-frame error the server reported. Cleared by the next good frame. */
  frameError: string | null;
}

/** ~5 fps. The backend's dwell times are in seconds, so this is not load-bearing. */
const CAPTURE_INTERVAL_MS = 200;
/** Width sent to the detector. MediaPipe finds a face well below this. */
const CAPTURE_WIDTH = 320;
const JPEG_QUALITY = 0.7;
/** After this long failing, stop calling it 'reconnecting' and admit it's down. */
const UNREACHABLE_AFTER_MS = 30_000;

const TERMINAL_CLOSE_CODES = new Set([1000, 4400]);

export function useDriverMonitor(
  driverCode: string | null,
  stream: MediaStream | null,
): DriverMonitorState {
  const [connection, setConnection] = useState<MonitorConnectionState>('connecting');
  const [reading, setReading] = useState<MonitorReading | null>(null);
  const [frameError, setFrameError] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const awaitingReplyRef = useRef(false);

  // A hidden <video> is the only way to get pixels out of a MediaStream that
  // works across browsers; `ImageCapture` is Chromium-only. It is created here
  // rather than rendered by the page so the visible preview element stays the
  // page's business and this hook does not depend on its layout.
  useEffect(() => {
    if (!stream) {
      return;
    }
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    videoRef.current = video;
    void video.play().catch(() => {
      // Autoplay refusal on a muted, script-created element is rare; if it
      // happens, capture simply yields no frames and the UI shows no reading.
    });

    const canvas = document.createElement('canvas');
    canvasRef.current = canvas;

    return () => {
      video.pause();
      video.srcObject = null;
      videoRef.current = null;
      canvasRef.current = null;
    };
  }, [stream]);

  const captureFrame = useCallback((): string | null => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
      return null;
    }
    const { videoWidth, videoHeight } = video;
    if (videoWidth === 0 || videoHeight === 0) {
      return null;
    }

    // Downscale preserving aspect ratio: EAR and MAR are ratios of distances
    // within one frame, so uniform scaling leaves them unchanged — but a
    // squashed frame would change them, and silently.
    const scale = CAPTURE_WIDTH / videoWidth;
    canvas.width = CAPTURE_WIDTH;
    canvas.height = Math.round(videoHeight * scale);

    const context = canvas.getContext('2d');
    if (!context) {
      return null;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/jpeg', JPEG_QUALITY);
  }, []);

  useEffect(() => {
    if (!driverCode || !stream) {
      setConnection('connecting');
      setReading(null);
      return;
    }

    let disposed = false;
    let attempt = 0;
    let openedAt = 0;
    let retryTimer: number | undefined;
    let captureTimer: number | undefined;
    let firstFailureAt: number | null = null;

    const clearTimers = (): void => {
      window.clearTimeout(retryTimer);
      window.clearInterval(captureTimer);
    };

    const startCapturing = (socket: WebSocket): void => {
      captureTimer = window.setInterval(() => {
        if (socket.readyState !== WebSocket.OPEN || awaitingReplyRef.current) {
          return;
        }
        const frame = captureFrame();
        if (!frame) {
          return;
        }
        awaitingReplyRef.current = true;
        socket.send(JSON.stringify({ frame }));
      }, CAPTURE_INTERVAL_MS);
    };

    const scheduleRetry = (): void => {
      firstFailureAt ??= Date.now();
      const downFor = Date.now() - firstFailureAt;
      setConnection(downFor >= UNREACHABLE_AFTER_MS ? 'unreachable' : 'reconnecting');

      const delay = nextDelayMs(attempt);
      attempt += 1;
      retryTimer = window.setTimeout(connect, delay);
    };

    function connect(): void {
      if (disposed) {
        return;
      }
      const socket = new WebSocket(
        buildWsUrl(`/ws/driver-monitor/${encodeURIComponent(driverCode!)}`),
      );
      socketRef.current = socket;
      awaitingReplyRef.current = false;

      socket.onopen = () => {
        openedAt = Date.now();
        firstFailureAt = null;
        setConnection('connected');
        startCapturing(socket);
      };

      socket.onmessage = (event: MessageEvent<string>) => {
        awaitingReplyRef.current = false;
        let message: MonitorMessage;
        try {
          message = JSON.parse(event.data) as MonitorMessage;
        } catch {
          return;
        }
        if (message.type === 'reading') {
          setReading(message);
          setFrameError(null);
        } else if (message.type === 'error') {
          setFrameError(message.detail);
        }
      };

      socket.onerror = () => {
        // Always followed by onclose, which is where the retry is decided.
        // Handling both would schedule two retries for one failure.
      };

      socket.onclose = (event: CloseEvent) => {
        window.clearInterval(captureTimer);
        awaitingReplyRef.current = false;
        socketRef.current = null;

        if (disposed) {
          return;
        }
        if (TERMINAL_CLOSE_CODES.has(event.code)) {
          setConnection('unreachable');
          return;
        }
        // Only a connection that actually held counts as a success worth
        // resetting the backoff for. See STABLE_CONNECTION_MS.
        if (openedAt > 0 && Date.now() - openedAt >= STABLE_CONNECTION_MS) {
          attempt = 0;
        }
        scheduleRetry();
      };
    }

    setConnection('connecting');
    connect();

    return () => {
      disposed = true;
      clearTimers();
      socketRef.current?.close(1000, 'client navigating away');
      socketRef.current = null;
    };
  }, [driverCode, stream, captureFrame]);

  return { connection, reading, frameError };
}
