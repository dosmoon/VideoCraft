/**
 * Shell — top-level renderer mount. A left activity bar (项目 / AI / 模型 / 设置)
 * switches the main view between the project Hub and the framework services. The
 * Hub stays mounted (display toggle) so an open workbench survives a detour into
 * the AI console or settings; the lighter framework views mount on demand.
 */

import { useEffect, useState } from "react";
import { Hub } from "./hub/Hub";
import { ActivityBar, type AppView } from "./app/ActivityBar";
import { AiConsole } from "./aiconsole/AiConsole";
import { ModelManager } from "./models/ModelManager";
import { Settings } from "./settings/Settings";
import { ConfirmHost } from "./ui/confirm";
import { VoicePickerHost } from "./ui/voicePicker";
import { tr, useLang } from "./i18n/tr";

export function Shell() {
  // Subscribe the whole tree to language changes so a hot switch re-renders
  // every tr() call below (no React.memo boundaries gate the views).
  const lang = useLang();
  const [view, setView] = useState<AppView>("project");

  // The native app menu lives in the main process but its labels are i18n —
  // re-send the translated set on mount and on every language switch (keyed on
  // `lang`), so the menu tracks the in-app language without restart.
  useEffect(() => {
    void window.vc.setMenu({
      file: tr("menu.file"),
      quit: tr("menu.quit"),
      view: tr("menu.view"),
      reload: tr("menu.reload"),
      devtools: tr("menu.devtools"),
      zoomReset: tr("menu.zoom_reset"),
      zoomIn: tr("menu.zoom_in"),
      zoomOut: tr("menu.zoom_out"),
      fullscreen: tr("menu.fullscreen"),
      help: tr("menu.help"),
      about: tr("menu.about"),
      github: tr("menu.github"),
      reportIssue: tr("menu.report_issue"),
    });
  }, [lang]);

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
      {view === "models" && (
        <div style={{ flex: 1, minWidth: 0, overflow: "auto" }}>
          <ModelManager />
        </div>
      )}
      {view === "settings" && (
        <div style={{ flex: 1, minWidth: 0, overflow: "auto" }}>
          <Settings />
        </div>
      )}
      {/* Single host for confirmDialog() — replaces native window.confirm so the
          OK/Cancel buttons follow the in-app language (Electron's native confirm
          chrome is locked to the OS locale). */}
      <ConfirmHost />
      {/* Single host for pickVoice() — the subtitle 合成音频 (TTS dub) action. */}
      <VoicePickerHost />
    </div>
  );
}
