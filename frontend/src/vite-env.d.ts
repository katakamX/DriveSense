/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Overrides the API base path. Defaults to the same-origin /api/v1 prefix. */
  readonly VITE_API_BASE_URL?: string;
  /**
   * Overrides the WebSocket origin + prefix (e.g. ws://localhost:8000/api/v1).
   * Takes precedence over VITE_API_BASE_URL for sockets; needed when the
   * socket does not live where the HTTP API does. See src/lib/ws/url.ts.
   */
  readonly VITE_WS_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
