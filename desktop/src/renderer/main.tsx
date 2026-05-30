import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Shell } from "./shell";

const root = document.getElementById("root");
if (!root) throw new Error("missing #root element");

createRoot(root).render(
  <StrictMode>
    <Shell />
  </StrictMode>,
);
