/**
 * Shell — top-level renderer mount. Renders the Hub (the product UI). The
 * WebGPU spike harness it used to sit beside has been retired now that the clip
 * workbench covers the same engine paths end-to-end; the harness's headless test
 * fixtures (src/renderer/harness/*.ts) live on for unit tests.
 */

import { Hub } from "./hub/Hub";
import { useLang } from "./i18n/tr";

export function Shell() {
  // Subscribe the whole tree to language changes so a hot switch re-renders
  // every tr() call below (no React.memo boundaries gate the workbenches).
  useLang();
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <Hub />
    </div>
  );
}
