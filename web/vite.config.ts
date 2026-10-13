import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
export default defineConfig({
  plugins: [react()],
  build: {
    license: { fileName: "THIRD-PARTY-NOTICES.md" },
    rolldownOptions: {
      output: {
        postBanner:
          "/* Bundled dependency licenses: /THIRD-PARTY-NOTICES.md */",
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: process.env.RECALLNEST_API_URL || "http://127.0.0.1:8787",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    include: ["src/**/*.test.tsx", "src/**/*.test.ts"],
    restoreMocks: true,
  },
});
