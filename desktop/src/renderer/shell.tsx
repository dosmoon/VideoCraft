/**
 * Shell — top-level renderer view switch. Defaults to the new Hub (product UI);
 * the WebGPU spike harness stays one click away. Additive on purpose: the Hub
 * doesn't swallow the harness, it sits beside it (the harness is still where the
 * engine/compositor spikes live). Each view mounts only when selected, so the
 * harness's heavy WebGPU init doesn't run unless you open it.
 */

import { useState } from "react";
import { Hub } from "./hub/Hub";
import { App as SpikeHarness } from "./app";

type View = "hub" | "harness";

export function Shell() {
  const [view, setView] = useState<View>("hub");
  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh" }}>
      <nav
        style={{
          display: "flex",
          gap: 4,
          padding: "6px 10px",
          borderBottom: "1px solid #2a2a2e",
          flexShrink: 0,
        }}
      >
        {(["hub", "harness"] as View[]).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            style={{
              padding: "3px 12px",
              fontSize: 12,
              fontWeight: view === v ? 700 : 400,
              background: view === v ? "#2d6cdf" : "transparent",
              color: view === v ? "#fff" : "#aaa",
              border: "none",
              borderRadius: 4,
              cursor: "pointer",
            }}
          >
            {v === "hub" ? "Hub" : "Spike harness"}
          </button>
        ))}
      </nav>
      <div style={{ flex: 1, overflow: "auto" }}>
        {view === "hub" ? <Hub /> : <SpikeHarness />}
      </div>
    </div>
  );
}
