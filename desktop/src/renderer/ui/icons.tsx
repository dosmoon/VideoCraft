/**
 * Icon vocabulary — the renderer's single source of UI icons (lucide-react).
 *
 * Introduced for the material sidebar redesign (ADR-0008 B3.2) to replace bare
 * emoji (inconsistent sizing, font-dependent, casual) with crisp, tintable SVG
 * icons. Components import semantic names from here instead of reaching into
 * lucide directly, so the icon set stays a deliberate, swappable vocabulary.
 *
 * Note: the analysis-type registry (`analysisTypes.ts`) keeps its emoji `icon`
 * field as data; the kind→lucide mapping lives here (presentation), so the shared
 * data layer is untouched.
 */

import {
  Film,
  Newspaper,
  Captions,
  Languages,
  ListTree,
  FileText,
  ListOrdered,
  Scissors,
  type LucideIcon,
} from "lucide-react";

// Re-export action / chrome icons so call sites have one import surface.
export {
  Sparkles,
  AudioLines,
  Languages,
  FileUp,
  Plus,
  ChevronRight,
  ChevronDown,
  ArrowLeft,
  Check,
  CheckCircle,
  Wrench,
  Loader2,
  AlertCircle,
  Folder,
  MoreHorizontal,
  Diamond,
  X,
} from "lucide-react";
export type { LucideIcon };

/** Slot-node icon by kind (source / news_context / subtitles). */
export const SLOT_ICON: Record<string, LucideIcon> = {
  source: Film,
  news_context: Newspaper,
  subtitles: Captions,
};

/** Subtitle-language node icon. */
export const LANG_ICON: LucideIcon = Languages;

const ANALYSIS_ICON: Record<string, LucideIcon> = {
  analysis: ListTree, // titles & chapters
  transcript: FileText, // full transcript
  chapter_transcript: ListOrdered, // per-chapter transcript
  hotclips: Scissors, // hot clips
};

/** Icon for an analysis kind; falls back to a generic document icon. */
export function analysisIcon(kind: string): LucideIcon {
  return ANALYSIS_ICON[kind] ?? FileText;
}
