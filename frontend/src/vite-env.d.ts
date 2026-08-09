/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Overrides the API base path. Defaults to the same-origin /api/v1 prefix. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
