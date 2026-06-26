/**
 * DubViewer — read-only view of a dubbing artifact (<lang>.dub.json manifest +
 * its <lang>.dub.mp3 audio). Pins an audio player at the top and lists the synth
 * summary (engine/voice, total length, cue counts, overflow). Mirrors the other
 * analysis viewers' chrome (DetailScaffold + pinned media).
 */

import { useEffect, useState } from "react";
import { rpc, RpcError } from "../../ipc/client";
import { tr } from "../../i18n/tr";
import { color, radius, font } from "../../ui/tokens";
import { DetailHeader, DetailScaffold } from "./detailChrome";

interface DubManifest {
  audio_file?: string;
  total_sec?: number;
  provider?: string;
  voice_id?: string;
  cue_count?: number;
  spoken_count?: number;
  overflow_count?: number;
  policy?: { mode?: string; max_speed?: number };
}

function fmtDuration(sec: number): string {
  const s = Math.max(0, Math.round(sec));
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ fontSize: font.sm, lineHeight: 1.6 }}>
      <span style={{ color: color.textMuted }}>{label} </span>
      <span style={{ color: color.textSecondary }}>{children}</span>
    </div>
  );
}

export function DubViewer(props: {
  type: string;
  instance: string;
  lang: string;
  title: string;
  onClose: () => void;
}) {
  const { type, instance, lang, title, onClose } = props;
  const [manifest, setManifest] = useState<DubManifest | null>(null);
  const [srcUrl, setSrcUrl] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const m = (await rpc.readAnalysis(type, instance, `${lang}.dub.json`)) as DubManifest;
        if (alive) setManifest(m);
        const path = await rpc.dubAudioPath(type, instance, lang);
        if (alive) setSrcUrl(path ? window.vc.mediaUrl(path) : "");
      } catch (err) {
        if (alive) setError(err instanceof RpcError ? `[${err.code}] ${err.message}` : String(err));
      }
    })();
    return () => {
      alive = false;
    };
  }, [type, instance, lang]);

  const pinned = srcUrl ? (
    <audio src={srcUrl} controls style={{ display: "block", width: "100%" }} />
  ) : undefined;

  const overflow = manifest?.overflow_count ?? 0;

  return (
    <DetailScaffold
      header={<DetailHeader title={title} subtitle={lang.toUpperCase()} onBack={onClose} />}
      pinned={pinned}
    >
      {error ? (
        <div style={{ color: color.danger, fontSize: font.sm }}>{error}</div>
      ) : !manifest ? (
        <div style={{ color: color.textMuted, fontSize: font.sm }}>{tr("material.dub.loading")}</div>
      ) : (
        <div
          style={{
            background: color.bgInset,
            border: `1px solid ${color.border}`,
            borderRadius: radius.sm,
            padding: 14,
          }}
        >
          <Stat label={tr("material.dub.stat_engine")}>
            {manifest.provider ?? "—"}
            {manifest.voice_id ? ` · ${manifest.voice_id}` : ""}
          </Stat>
          <Stat label={tr("material.dub.stat_total")}>{fmtDuration(manifest.total_sec ?? 0)}</Stat>
          <Stat label={tr("material.dub.stat_cues")}>
            {manifest.spoken_count ?? 0} / {manifest.cue_count ?? 0}
          </Stat>
          <Stat label={tr("material.dub.stat_overflow")}>
            <span style={{ color: overflow > 0 ? color.warn : color.textSecondary }}>{overflow}</span>
          </Stat>
        </div>
      )}
    </DetailScaffold>
  );
}
