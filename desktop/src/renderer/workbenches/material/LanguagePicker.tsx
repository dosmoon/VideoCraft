/**
 * LanguagePicker — editable combobox over the preset language catalog
 * (system.list_languages / core.lang_names.WHISPER_LANG_CHOICES). Mirrors the Tk
 * ttk.Combobox used for ASR source / translate target / import language: typing
 * filters the presets (by iso or friendly name) and selection stores the iso, so
 * a manual entry snaps to a preset code rather than being free text.
 *
 * `allowAuto` prepends an "自动检测" row that maps to "" (ASR auto-detect).
 */

import { useEffect, useRef, useState } from "react";
import type { KnownLanguage } from "../../ipc/client";

const INPUT: React.CSSProperties = {
  padding: "4px 8px",
  background: "#1a1a1e",
  color: "#ddd",
  border: "1px solid #333",
  borderRadius: 4,
  fontSize: 13,
  width: "100%",
  boxSizing: "border-box",
};

export function LanguagePicker(props: {
  value: string; // iso, "" = none / auto
  onChange: (iso: string) => void;
  languages: KnownLanguage[];
  placeholder?: string;
  disabled?: boolean;
  allowAuto?: boolean;
  width?: number;
}) {
  const { value, onChange, languages, placeholder, disabled, allowAuto, width } = props;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const wrapRef = useRef<HTMLDivElement | null>(null);

  const displayOf = (iso: string): string => {
    if (!iso) return allowAuto ? "自动检测" : "";
    return languages.find((l) => l.iso === iso)?.display ?? iso;
  };

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  const q = query.trim().toLowerCase();
  const matches = q
    ? languages.filter((l) => l.iso.toLowerCase().includes(q) || l.display.toLowerCase().includes(q))
    : languages;
  const options: KnownLanguage[] = allowAuto ? [{ iso: "", display: "自动检测" }, ...matches] : matches;

  const pick = (iso: string) => {
    onChange(iso);
    setQuery("");
    setOpen(false);
  };

  return (
    <div ref={wrapRef} style={{ position: "relative", width: width ?? 200 }}>
      <input
        value={open ? query : displayOf(value)}
        placeholder={placeholder}
        disabled={disabled}
        onFocus={() => {
          setQuery("");
          setOpen(true);
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        style={INPUT}
      />
      {open && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            left: 0,
            right: 0,
            zIndex: 30,
            marginTop: 2,
            maxHeight: 240,
            overflowY: "auto",
            background: "#1f1f23",
            border: "1px solid #3a3a40",
            borderRadius: 6,
            boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
          }}
        >
          {options.length === 0 ? (
            <div style={{ padding: "6px 8px", color: "#888", fontSize: 12 }}>无匹配语言</div>
          ) : (
            options.slice(0, 60).map((l) => (
              <button
                key={l.iso || "__auto__"}
                onMouseDown={(e) => {
                  e.preventDefault(); // keep focus / fire before blur
                  pick(l.iso);
                }}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: "5px 8px",
                  background: l.iso === value ? "#2d6cdf" : "transparent",
                  color: l.iso === value ? "#fff" : "#ddd",
                  border: "none",
                  fontSize: 12,
                  cursor: "pointer",
                }}
              >
                {l.display}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
