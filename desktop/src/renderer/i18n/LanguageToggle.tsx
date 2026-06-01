/**
 * LanguageToggle — a compact 中 / EN segmented control. Switching is HOT: it
 * calls setLang (re-renders the tree via useLang subscribers) and persists the
 * choice back to settings.json (system.set_locale) so it survives restart and
 * stays in lockstep with the Tk app. Persistence is best-effort — the UI flips
 * immediately regardless.
 */

import { getLang, setLang, useLang, type Lang } from "./tr";
import { rpc } from "../ipc/client";

const OPTIONS: { code: Lang; label: string }[] = [
  { code: "zh", label: "中" },
  { code: "en", label: "EN" },
];

export function LanguageToggle() {
  const lang = useLang();
  const pick = (code: Lang) => {
    if (code === getLang()) return;
    setLang(code);
    void rpc.setLocale(code).catch(() => {
      /* persistence is best-effort; the UI already switched */
    });
  };
  return (
    <div
      style={{
        display: "inline-flex",
        borderRadius: 5,
        border: "1px solid #3a3a40",
        overflow: "hidden",
      }}
      role="group"
      aria-label="Language"
    >
      {OPTIONS.map((o) => {
        const active = lang === o.code;
        return (
          <button
            key={o.code}
            onClick={() => pick(o.code)}
            aria-pressed={active}
            style={{
              padding: "3px 9px",
              fontSize: 12,
              lineHeight: "16px",
              border: "none",
              background: active ? "#2d6cdf" : "transparent",
              color: active ? "#fff" : "#aaa",
              cursor: active ? "default" : "pointer",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
