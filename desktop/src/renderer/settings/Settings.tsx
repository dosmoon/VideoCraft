/**
 * Settings — the ⚙ panel. Three sections, ported from the Tk Preferences tool:
 *   - Language: the single canonical home for the 中/EN switch (hot, persists to
 *     the same settings.json). The per-page toggles were removed in favor of this.
 *   - Environment: external dependency dashboard (ffmpeg / Node / yt-dlp / SDKs),
 *     detect + one-click install (jobs; install streams its log).
 *   - About: app identity.
 */

import { useCallback, useEffect, useState } from "react";
import { rpc, RpcError, type EnvComponentMeta, type EnvDetect } from "../ipc/client";
import { runJob } from "../ipc/runJob";
import { LanguageToggle } from "../i18n/LanguageToggle";
import { tr } from "../i18n/tr";

const CARD: React.CSSProperties = {
  border: "1px solid #2a2a2e",
  borderRadius: 6,
  padding: "10px 12px",
  marginBottom: 8,
};
const BTN: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ddd",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  fontSize: 12,
  padding: "3px 10px",
  cursor: "pointer",
};
const H3: React.CSSProperties = { fontSize: 13, color: "#ccc", margin: "18px 0 8px", fontWeight: 700 };

function fmtErr(e: unknown): string {
  if (e instanceof RpcError) return `[${e.code}] ${e.message}`;
  return e instanceof Error ? e.message : String(e);
}

export function Settings() {
  return (
    <div style={{ padding: "16px 20px", maxWidth: 720, margin: "0 auto" }}>
      <h2 style={{ fontWeight: 600, margin: "0 0 4px" }}>{tr("settings.title")}</h2>

      <h3 style={H3}>{tr("settings.section_language")}</h3>
      <div style={{ ...CARD, display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 13 }}>{tr("settings.language")}</span>
        <LanguageToggle />
        <span style={{ fontSize: 11, color: "#777" }}>{tr("settings.language_hint")}</span>
      </div>

      <EnvSection />

      <AboutSection />
    </div>
  );
}

function AboutSection() {
  const [bi, setBi] = useState<BuildInfo | null>(null);
  const [ai, setAi] = useState<AppInfo | null>(null);
  useEffect(() => {
    // Static, host-side metadata (not the sidecar) — one roundtrip each, no spinner.
    void window.vc.buildInfo().then(setBi).catch(() => {});
    void window.vc.appInfo().then(setAi).catch(() => {});
  }, []);
  return (
    <>
      <h3 style={H3}>{tr("settings.section_about")}</h3>
      <div style={CARD}>
        <div style={{ fontWeight: 600 }}>{ai?.name ?? "VideoCraft"}</div>
        <div style={{ fontSize: 12, color: "#888", marginTop: 4 }}>{tr("settings.about_blurb")}</div>
        {bi && (
          <div
            style={{ fontSize: 11, color: "#666", marginTop: 6, fontFamily: "monospace" }}
            title={bi.builtAt || undefined}
          >
            {tr("settings.build_line", { version: bi.version, build: bi.build, commit: bi.commit || "—" })}
          </div>
        )}
        {ai && (
          <div style={{ fontSize: 11, color: "#888", marginTop: 8, lineHeight: 1.6 }}>
            <div>{tr("settings.about_by", { author: ai.author, org: ai.org })}</div>
            <div style={{ color: "#666" }}>
              {tr("settings.about_copyright", { copyright: ai.copyright, license: ai.license })}
            </div>
            {ai.homepage && (
              <span
                onClick={() => void window.vc.openExternal(ai.homepage)}
                style={{ color: "#6aa6ff", cursor: "pointer" }}
              >
                {ai.homepage.replace(/^https?:\/\//, "")}
              </span>
            )}
          </div>
        )}
      </div>
    </>
  );
}

function EnvSection() {
  const [comps, setComps] = useState<EnvComponentMeta[] | null>(null);
  const [detect, setDetect] = useState<Record<string, EnvDetect>>({});
  const [detecting, setDetecting] = useState(false);
  const [error, setError] = useState("");

  const detectAll = useCallback(async () => {
    setDetecting(true);
    setError("");
    try {
      const h = await runJob<{ results: EnvDetect[] }>(
        () => rpc.envDetectAll(),
        (p) => {
          // Each component streams its result as it's detected — fill the row
          // now instead of waiting for the whole batch (binary version probes
          // can each block up to 5s).
          const d = p.result as EnvDetect | undefined;
          if (d?.id) setDetect((prev) => ({ ...prev, [d.id]: d }));
        },
      );
      const r = await h.promise;
      setDetect(Object.fromEntries(r.results.map((d) => [d.id, d])));
    } catch (e) {
      setError(fmtErr(e));
    } finally {
      setDetecting(false);
    }
  }, []);

  useEffect(() => {
    rpc
      .envComponents()
      .then((c) => {
        setComps(c);
        void detectAll();
      })
      .catch((e) => setError(fmtErr(e)));
  }, [detectAll]);

  const onDetected = (d: EnvDetect) => setDetect((prev) => ({ ...prev, [d.id]: d }));

  return (
    <>
      <div style={{ ...H3, display: "flex", alignItems: "center", gap: 10 }}>
        <span>{tr("settings.section_env")}</span>
        <button onClick={() => void detectAll()} disabled={detecting} style={{ ...BTN, fontWeight: 400 }}>
          {detecting ? tr("settings.detecting") : tr("settings.refresh")}
        </button>
      </div>
      {error && <p style={{ color: "#ff6b6b" }}>✗ {error}</p>}
      {comps === null ? (
        <p style={{ color: "#888" }}>{tr("common.loading")}</p>
      ) : (
        comps.map((c) => (
          <EnvRow
            key={c.id}
            meta={c}
            detect={detect[c.id]}
            detecting={detecting && !detect[c.id]}
            onDetected={onDetected}
          />
        ))
      )}
    </>
  );
}

function EnvRow({
  meta,
  detect,
  detecting,
  onDetected,
}: {
  meta: EnvComponentMeta;
  detect: EnvDetect | undefined;
  detecting: boolean;
  onDetected: (d: EnvDetect) => void;
}) {
  const [installing, setInstalling] = useState(false);
  const [line, setLine] = useState("");
  const [err, setErr] = useState("");

  const install = async () => {
    setInstalling(true);
    setErr("");
    setLine("");
    try {
      const h = await runJob<EnvDetect>(
        () => rpc.envInstall(meta.id),
        (p) => p.line && setLine(String(p.line)),
      );
      onDetected(await h.promise);
    } catch (e) {
      setErr(fmtErr(e));
    } finally {
      setInstalling(false);
    }
  };

  const ok = detect?.available;
  const status = detecting
    ? tr("settings.detecting")
    : ok
      ? `✓ ${detect?.version ?? ""}${detect?.source ? ` (${tr(`env.source.${detect.source}`)})` : ""}`
      : `✗ ${tr("settings.missing")}`;

  return (
    <div style={CARD}>
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{tr(`env.component.${meta.id}`)}</span>
        <span style={{ fontSize: 11, color: "#777" }}>{meta.category}</span>
        <span style={{ marginLeft: "auto", fontSize: 12, color: ok ? "#7fd17f" : "#d98b8b" }}>{status}</span>
        {meta.installable && (
          // Available installable components (e.g. the bundled yt-dlp) still get a
          // button — it re-runs the install, which always upgrades into py-extra so
          // the user can track upstream releases (yt-dlp vs YouTube changes).
          <button onClick={install} disabled={installing} style={{ ...BTN, background: "#2d6cdf", color: "#fff", border: "none" }}>
            {installing
              ? tr(ok ? "settings.updating" : "settings.installing")
              : tr(ok ? "settings.update" : "settings.install")}
          </button>
        )}
        {meta.info_url && !ok && (
          // "Guide" = where to get it; only useful when it's missing. A present
          // binary (e.g. bundled ffmpeg) needs no install guide.
          <button onClick={() => void window.vc.openExternal(meta.info_url!)} style={BTN}>
            {tr("settings.guide")}
          </button>
        )}
      </div>
      {installing && line && (
        <div style={{ fontSize: 11, color: "#888", marginTop: 6, fontFamily: "monospace", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {line}
        </div>
      )}
      {err && <div style={{ fontSize: 11, color: "#d98b8b", marginTop: 4 }}>✗ {err}</div>}
    </div>
  );
}
