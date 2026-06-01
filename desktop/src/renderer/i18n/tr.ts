/**
 * tr.ts — lightweight renderer-side localization, mirroring the Tk `src/i18n.py`
 * mental model (flat <lang>.json tables + a single tr(key, vars?) lookup).
 *
 * Both locale tables are bundled statically (import) so tr() is synchronous and
 * usable from any component without a provider. The active language is a module
 * singleton, seeded once at boot (main.tsx awaits `system.get_locale` from the
 * sidecar — same settings.json the Tk app reads — then calls setLang before the
 * first render). Unlike Tk (labels fixed at widget-creation → restart to switch),
 * the renderer evaluates tr() every render, so switching is HOT: setLang notifies
 * subscribers (useLang / a top-level useLang in Shell) → the tree re-renders →
 * every tr() call re-reads the new table. The language picker also persists the
 * choice back to settings.json (system.set_locale) so it survives restart and
 * stays in lockstep with the Tk app.
 *
 * Fallback chain for any key:  current-lang table → en table → raw key string.
 * Interpolation uses {name} placeholders (parity with Python str.format kwargs).
 */

import { useSyncExternalStore } from "react";
import zh from "./zh.json";
import en from "./en.json";

export type Lang = "zh" | "en";

const TABLES: Record<Lang, Record<string, string>> = { zh, en };
const DEFAULT_LANG: Lang = "en";

let _lang: Lang = DEFAULT_LANG;
const listeners = new Set<() => void>();

/** Set the active language and notify subscribers (hot re-render). No-op if unchanged. */
export function setLang(code: string): void {
  const next: Lang = code === "zh" || code === "en" ? code : DEFAULT_LANG;
  if (next === _lang) return;
  _lang = next;
  for (const cb of listeners) cb();
}

export function getLang(): Lang {
  return _lang;
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/**
 * Subscribe a component to language changes. A top-level call (e.g. in Shell)
 * makes the whole tree re-render on switch; the language picker calls it to
 * reflect the active choice. Returns the current language.
 */
export function useLang(): Lang {
  return useSyncExternalStore(subscribe, getLang);
}

export function tr(key: string, vars?: Record<string, string | number>): string {
  let text = TABLES[_lang][key];
  if (text === undefined) text = TABLES[DEFAULT_LANG][key];
  if (text === undefined) return key;
  if (vars) {
    text = text.replace(/\{(\w+)\}/g, (m, name: string) =>
      name in vars ? String(vars[name]) : m,
    );
  }
  return text;
}
