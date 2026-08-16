/**
 * Cabin camera access via `getUserMedia`.
 *
 * Split from the frame-capture hook because the two fail for unrelated
 * reasons and at unrelated times: a denied camera permission is permanent
 * until the user changes it in browser settings, while a dropped WebSocket is
 * transient and retried. Folding them into one state would mean one error
 * banner having to explain both.
 *
 * Note `getUserMedia` is only available in a secure context — `https://` or
 * `localhost`. Opening the dev server on a LAN IP will fail here with
 * `unsupported`, which is a browser rule, not a bug in this code.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

export type WebcamState = 'idle' | 'requesting' | 'ready' | 'denied' | 'unsupported' | 'error';

export interface Webcam {
  state: WebcamState;
  stream: MediaStream | null;
  error: string | null;
  /** Request access. Safe to call again after a failure. */
  start: () => void;
  stop: () => void;
}

const CONSTRAINTS: MediaStreamConstraints = {
  // 640×480 is well above the ~320 px the detector is sent, leaving headroom
  // for the preview to look sharp while the wire stays small.
  video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' },
  audio: false,
};

export function useWebcam(): Webcam {
  const [state, setState] = useState<WebcamState>('idle');
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setStream(null);
    setState('idle');
  }, []);

  const start = useCallback(() => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setState('unsupported');
      setError('This browser does not expose a camera API, or the page is not on a secure origin.');
      return;
    }

    setState('requesting');
    setError(null);

    navigator.mediaDevices
      .getUserMedia(CONSTRAINTS)
      .then((granted) => {
        // The component may have unmounted or called stop() while the
        // permission prompt was open. Releasing the camera here is the only
        // chance to do it — nothing else holds a reference to this stream.
        if (streamRef.current === null && !mountedRef.current) {
          granted.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = granted;
        setStream(granted);
        setState('ready');
      })
      .catch((cause: unknown) => {
        const name = cause instanceof DOMException ? cause.name : '';
        if (name === 'NotAllowedError' || name === 'SecurityError') {
          setState('denied');
          setError('Camera access was blocked. Allow it in the browser and try again.');
        } else if (name === 'NotFoundError' || name === 'OverconstrainedError') {
          setState('error');
          setError('No camera was found on this device.');
        } else {
          setState('error');
          setError(cause instanceof Error ? cause.message : 'The camera could not be opened.');
        }
      });
  }, []);

  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      // Tracks outlive React state, and a camera left running keeps the
      // browser's recording indicator lit after the page has moved on.
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, []);

  return { state, stream, error, start, stop };
}
