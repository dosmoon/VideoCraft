import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Shell } from "./shell";
import { rpc } from "./ipc/client";
import { setLang } from "./i18n/tr";
import "./ui/anim.css";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root element");

// Resolve the UI language from the sidecar (same settings.json the Tk app reads)
// before the first render so labels paint in the right language with no flash.
// On any failure we fall back to the tr() default (en) rather than block boot.
async function boot() {
  try {
    const { lang } = await rpc.getLocale();
    setLang(lang);
  } catch {
    // sidecar not ready / unsupported — keep the default locale.
  }
  createRoot(root!).render(
    <StrictMode>
      <Shell />
    </StrictMode>,
  );
}

void boot();
