/**
 * confirm.tsx — in-app confirmation dialog with i18n buttons.
 *
 * Why not window.confirm(): Electron renders native confirm/alert chrome
 * (the OK/Cancel buttons) from Chromium's locale, which follows the OS — on a
 * Chinese Windows the buttons read 确定/取消 even when the app UI is switched to
 * English. Only the *message* we pass is localizable; the buttons are not. So a
 * native confirm can never honor the in-app language toggle ([[tr]] / setLang).
 *
 * This module replaces window.confirm with a React modal whose buttons go
 * through tr(), so they track the in-app language like everything else. The API
 * is imperative to stay a near drop-in for the old call sites:
 *
 *     if (!(await confirmDialog(tr("...")))) return;
 *
 * A single <ConfirmHost /> mounted at the Shell root renders whatever the
 * pending confirmDialog() call requested. Enter confirms, Escape / overlay-click
 * cancels.
 */

import { useEffect } from "react";
import { useSyncExternalStore } from "react";
import { tr } from "../i18n/tr";
import { color, radius, font, space } from "./tokens";

type ConfirmRequest = {
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  resolve: (ok: boolean) => void;
};

let current: ConfirmRequest | null = null;
const listeners = new Set<() => void>();

function emit(): void {
  for (const cb of listeners) cb();
}

/**
 * Show a confirmation dialog and resolve true (confirmed) / false (cancelled).
 * Pass `confirmLabel` / `cancelLabel` to override the default OK / Cancel; both
 * default to the shared i18n strings so buttons follow the in-app language.
 *
 * Requires <ConfirmHost /> mounted once near the app root.
 */
export function confirmDialog(
  message: string,
  opts?: { confirmLabel?: string; cancelLabel?: string },
): Promise<boolean> {
  return new Promise<boolean>((resolve) => {
    // Defensive: if one is somehow already open, cancel it before replacing so
    // its awaiter doesn't hang.
    if (current) current.resolve(false);
    current = {
      message,
      confirmLabel: opts?.confirmLabel ?? tr("common.ok"),
      cancelLabel: opts?.cancelLabel ?? tr("common.cancel"),
      resolve,
    };
    emit();
  });
}

function settle(ok: boolean): void {
  const req = current;
  current = null;
  emit();
  req?.resolve(ok);
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

/**
 * Host for confirmDialog() — mount once at the app root. Renders nothing until a
 * confirm is pending, then shows the modal. Keyboard: Enter confirms, Escape
 * cancels.
 */
export function ConfirmHost(): React.ReactElement | null {
  const req = useSyncExternalStore(subscribe, () => current);

  useEffect(() => {
    if (!req) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        settle(false);
      } else if (e.key === "Enter") {
        e.preventDefault();
        settle(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [req]);

  if (!req) return null;

  return (
    <div
      onClick={() => settle(false)}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        style={{
          background: color.bgRaised,
          border: `1px solid ${color.border}`,
          borderRadius: radius.md,
          padding: 20,
          minWidth: 320,
          maxWidth: 480,
          boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
        }}
      >
        <p
          style={{
            margin: 0,
            color: color.textPrimary,
            fontSize: font.lg,
            lineHeight: 1.5,
            whiteSpace: "pre-wrap",
          }}
        >
          {req.message}
        </p>
        <div
          style={{
            display: "flex",
            justifyContent: "flex-end",
            gap: space.lg,
            marginTop: 20,
          }}
        >
          <button
            onClick={() => settle(false)}
            style={{
              background: color.bgHover,
              color: color.textPrimary,
              border: `1px solid ${color.border}`,
              borderRadius: radius.sm,
              padding: "6px 16px",
              fontSize: font.md,
              cursor: "pointer",
            }}
          >
            {req.cancelLabel}
          </button>
          <button
            autoFocus
            onClick={() => settle(true)}
            style={{
              background: color.accent,
              color: "#fff",
              border: "none",
              borderRadius: radius.sm,
              padding: "6px 16px",
              fontSize: font.md,
              cursor: "pointer",
            }}
          >
            {req.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
