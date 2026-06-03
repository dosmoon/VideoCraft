/**
 * Export settings bar — engine + resolution + fps + bitrate controls shared by
 * the clip and news_desk export tabs. Presentational: it reads the current
 * ExportSettings and emits a partial patch on change; the tab maps that to the
 * right config wire keys (clip resolution → output_short_edge; news_desk →
 * export_resolution) and persists via rpc.updateConfig.
 */

import { tr } from "../../i18n/tr";
import {
  FPS_PRESETS,
  type ExportSettings,
  type FfmpegProbe,
} from "@creations/exportSettings";

function resLabel(token: string): string {
  return token === "source" ? tr("export.resolution.source") : `${token}p`;
}

export function ExportSettingsBar(props: {
  settings: ExportSettings;
  probe: FfmpegProbe | null;
  resolutionOptions: readonly string[];
  disabled?: boolean;
  onChange: (patch: Partial<ExportSettings>) => void;
}) {
  const { settings, probe, resolutionOptions, disabled, onChange } = props;
  const ffmpegOk = !!probe?.ffmpeg;
  const ffmpegLabel = ffmpegOk
    ? `ffmpeg (${probe?.nvenc ? "NVENC" : "libx264"})`
    : `ffmpeg — ${tr("export.engine.unavailable")}`;

  return (
    <div style={wrap}>
      <span style={heading}>{tr("export.settings.heading")}</span>

      <label style={field}>
        <span style={lbl}>{tr("export.engine.label")}</span>
        <select
          value={settings.engine}
          disabled={disabled}
          onChange={(e) => onChange({ engine: e.target.value as ExportSettings["engine"] })}
          style={sel}
        >
          <option value="">{tr("export.engine.auto")}</option>
          <option value="chromium">Chromium</option>
          <option value="ffmpeg" disabled={!ffmpegOk}>{ffmpegLabel}</option>
        </select>
      </label>

      <label style={field}>
        <span style={lbl}>{tr("export.resolution.label")}</span>
        <select
          value={settings.resolution}
          disabled={disabled}
          onChange={(e) => onChange({ resolution: e.target.value })}
          style={sel}
        >
          {resolutionOptions.map((r) => (
            <option key={r} value={r}>{resLabel(r)}</option>
          ))}
        </select>
      </label>

      <label style={field}>
        <span style={lbl}>{tr("export.fps.label")}</span>
        <select
          value={String(settings.fps)}
          disabled={disabled}
          onChange={(e) => onChange({ fps: Number(e.target.value) })}
          style={sel}
        >
          {FPS_PRESETS.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
      </label>

      <label style={field}>
        <span style={lbl}>{tr("export.bitrate.label")}</span>
        <select
          value={settings.bitrateMode}
          disabled={disabled}
          onChange={(e) => onChange({ bitrateMode: e.target.value as ExportSettings["bitrateMode"] })}
          style={sel}
        >
          <option value="auto">{tr("export.bitrate.auto")}</option>
          <option value="mbps">{tr("export.bitrate.mbps")}</option>
        </select>
        {settings.bitrateMode === "mbps" && (
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <input
              type="number"
              min={1}
              max={200}
              value={settings.bitrateMbps}
              disabled={disabled}
              onChange={(e) => onChange({ bitrateMbps: Number(e.target.value) })}
              style={num}
            />
            <span style={{ color: "#888", fontSize: 12 }}>{tr("export.bitrate.mbps_unit")}</span>
          </span>
        )}
      </label>
    </div>
  );
}

const wrap: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: 12,
  padding: "8px 10px",
  marginBottom: 12,
  border: "1px solid #2a2a2e",
  borderRadius: 6,
  background: "#1c1c20",
};
const heading: React.CSSProperties = {
  fontSize: 11,
  color: "#888",
  fontWeight: 700,
  textTransform: "uppercase",
};
const field: React.CSSProperties = { display: "inline-flex", alignItems: "center", gap: 6 };
const lbl: React.CSSProperties = { fontSize: 12, color: "#aaa" };
const sel: React.CSSProperties = {
  background: "#2a2a2e",
  color: "#ddd",
  border: "1px solid #3a3a40",
  borderRadius: 4,
  padding: "3px 6px",
  fontSize: 12,
};
const num: React.CSSProperties = { ...sel, width: 64 };
