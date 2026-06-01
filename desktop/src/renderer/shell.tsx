/**
 * Shell — top-level renderer mount. A left activity bar (项目 / AI / 模型 / 设置)
 * switches the main view between the project Hub and the framework services. The
 * Hub stays mounted (display toggle) so an open workbench survives a detour into
 * the AI console or settings; the lighter framework views mount on demand.
 */

import { useState } from "react";
import { Hub } from "./hub/Hub";
import { ActivityBar, type AppView } from "./app/ActivityBar";
import { AiConsole } from "./aiconsole/AiConsole";
import { useLang, tr } from "./i18n/tr";

function Placeholder({ titleKey }: { titleKey: string }) {
  return (
    <div style={{ flex: 1, display: "grid", placeItems: "center", color: "#666", fontSize: 14 }}>
      {tr(titleKey)}
    </div>
  );
}

export function Shell() {
  // Subscribe the whole tree to language changes so a hot switch re-renders
  // every tr() call below (no React.memo boundaries gate the views).
  useLang();
  const [view, setView] = useState<AppView>("project");

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <ActivityBar view={view} onSelect={setView} />
      {/* Hub is always mounted (display toggle) to preserve project/workbench state. */}
      <div
        style={{
          flex: 1,
          minWidth: 0,
          display: view === "project" ? "flex" : "none",
          flexDirection: "column",
        }}
      >
        <Hub />
      </div>
      {/* Framework views mount on demand (cheap; their writes persist immediately). */}
      {view === "ai" && (
        <div style={{ flex: 1, minWidth: 0, overflow: "auto" }}>
          <AiConsole />
        </div>
      )}
      {view === "models" && <Placeholder titleKey="shell.models_soon" />}
      {view === "settings" && <Placeholder titleKey="shell.settings_soon" />}
    </div>
  );
}
