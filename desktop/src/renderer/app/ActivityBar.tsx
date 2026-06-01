/**
 * ActivityBar — the left icon rail (VSCode-style) that switches the main view
 * between the project Hub and the framework services (AI console, model manager,
 * preferences). The Hub stays mounted across switches (display toggle in Shell)
 * so an open workbench survives a peek at settings.
 */

import { tr } from "../i18n/tr";

export type AppView = "project" | "ai" | "models" | "settings";

const ITEMS: { view: AppView; icon: string; labelKey: string }[] = [
  { view: "project", icon: "📁", labelKey: "shell.nav.project" },
  { view: "ai", icon: "🤖", labelKey: "shell.nav.ai" },
  { view: "models", icon: "📦", labelKey: "shell.nav.models" },
  { view: "settings", icon: "⚙", labelKey: "shell.nav.settings" },
];

export function ActivityBar({
  view,
  onSelect,
}: {
  view: AppView;
  onSelect: (v: AppView) => void;
}) {
  return (
    <nav
      style={{
        width: 56,
        flexShrink: 0,
        background: "#161619",
        borderRight: "1px solid #2a2a2e",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        paddingTop: 8,
        gap: 4,
      }}
    >
      {ITEMS.map((it) => {
        const active = view === it.view;
        return (
          <button
            key={it.view}
            onClick={() => onSelect(it.view)}
            title={tr(it.labelKey)}
            aria-label={tr(it.labelKey)}
            aria-pressed={active}
            style={{
              width: 40,
              height: 40,
              borderRadius: 8,
              border: "none",
              background: active ? "#2d6cdf" : "transparent",
              color: active ? "#fff" : "#aaa",
              fontSize: 18,
              cursor: "pointer",
            }}
          >
            {it.icon}
          </button>
        );
      })}
    </nav>
  );
}
