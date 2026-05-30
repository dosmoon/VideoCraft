/**
 * Shell — top-level renderer mount. Renders the Hub (the product UI). The
 * WebGPU spike harness it used to sit beside has been retired now that the clip
 * workbench covers the same engine paths end-to-end; the harness's headless test
 * fixtures (src/renderer/harness/*.ts) live on for unit tests.
 */

import { Hub } from "./hub/Hub";

export function Shell() {
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <Hub />
    </div>
  );
}
