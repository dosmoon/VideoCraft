/**
 * Shared design tokens for the renderer.
 *
 * The renderer historically had zero CSS / design system — every component
 * inlined ad-hoc hex, which is why the surfaces drift and crowd. This module is
 * the single source of color/spacing/radius for new work (introduced for the
 * material sidebar redesign, ADR-0008 B3.2). Existing components can adopt it
 * incrementally; nothing forces a global refactor.
 *
 * Palette is anchored to the app base (`index.html`: bg #111 / text #eee, accent
 * #2d6cdf) so tokenized surfaces sit coherently on the existing chrome.
 */

export const color = {
  bg: "#111111", // app base (matches index.html body)
  bgInset: "#16161a", // recessed surfaces: cards, code/preview blocks
  bgRaised: "#1f1f23", // popovers / menus
  bgHover: "#26262b", // row hover, ghost-button rest
  border: "#3a3a40",
  borderSubtle: "#2a2a2e",
  textPrimary: "#e6e6ea",
  textSecondary: "#aaadb3",
  textMuted: "#777a80",
  accent: "#2d6cdf",
  accentSoft: "rgba(45,108,223,0.16)", // selected-row fill (replaces solid blue)
  accentText: "#9cc0ff", // selected label text on the soft fill
  success: "#3fb27f",
  warn: "#d9a23a",
  danger: "#e0726b",
} as const;

/** State color for a slot/node icon: empty → partial → done, plus locked. */
export const state = {
  empty: color.textMuted,
  partial: color.warn,
  done: color.success,
  locked: "#5a5c62",
} as const;

export const space = { xs: 2, sm: 4, md: 6, lg: 8, xl: 12 } as const;
export const radius = { sm: 4, md: 6, pill: 999 } as const;
export const font = { xs: 11, sm: 12, md: 13, lg: 14 } as const;
