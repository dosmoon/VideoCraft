import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { defineConfig } from "vitest/config";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  // Mirror the renderer aliases so harness/engine code that imports the
  // pure-logic layer via @composition/@creations is unit-testable headlessly.
  resolve: {
    alias: {
      "@composition": resolve(root, "src/composition"),
      "@creations": resolve(root, "src/creations"),
      "@materials": resolve(root, "src/materials"),
    },
  },
  test: {
    globals: true,
    include: ["src/**/*.test.ts"],
  },
});
