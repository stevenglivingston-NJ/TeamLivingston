import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Mobile-first SPA served at ktubloomfield.com/tuneup. `base` keeps asset URLs
// under /tuneup/ so the app can live on a subpath of the marketing domain.
export default defineConfig({
  base: "/tuneup/",
  plugins: [react()],
  server: {
    // Proxy /api to the local Worker (wrangler dev on :8787) during development.
    proxy: { "/api": "http://localhost:8787" },
  },
});
