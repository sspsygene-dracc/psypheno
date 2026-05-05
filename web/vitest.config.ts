import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./vitest.setup.ts"],
    env: {
      SSPSYGENE_DATA_DB:
        process.env.SSPSYGENE_DATA_DB ??
        "/Users/jbirgmei/prog/sspsygene/data/db/sspsygene.db",
    },
    include: [
      "lib/**/*.test.ts",
      "lib/**/__tests__/**/*.test.ts",
      "pages/api/**/*.test.ts",
      "pages/api/**/__tests__/**/*.test.ts",
    ],
  },
});
