/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** GA4 measurement id (G-XXXXXXX); gtag stays a no-op until set. */
  readonly VITE_GA4_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
