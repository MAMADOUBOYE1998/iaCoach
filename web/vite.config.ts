import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // getUserMedia requires a secure context. localhost counts as secure, so
    // plain http is fine for desktop dev; testing on a phone over the LAN needs
    // HTTPS (see docs/ROADMAP.md, M0 notes).
    host: true,
    port: 5173,
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
});
