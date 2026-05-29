/**
 * Shared video-component library — public surface + registry.
 *
 * The single catalog of reusable video components (foundation doc §4.5). A
 * creation plugin picks a subset and maps its own config/analysis onto each
 * component's canonical instance; the components themselves and their
 * compile→OTIO live here once.
 */

export * from "./contract.js";
export * from "./subtitle.js";
export * from "./watermark.js";
export * from "./card.js";
export * from "./chapter.js";

import type { VideoComponent } from "./contract.js";
import { subtitle } from "./subtitle.js";
import { textWatermark, imageWatermark } from "./watermark.js";
import { hookCard, outroCard } from "./card.js";
import { chapter } from "./chapter.js";

/** All shared components keyed by canonical kind. */
export const COMPONENT_REGISTRY: Readonly<Record<string, VideoComponent<unknown>>> = {
  [subtitle.kind]: subtitle as VideoComponent<unknown>,
  [textWatermark.kind]: textWatermark as VideoComponent<unknown>,
  [imageWatermark.kind]: imageWatermark as VideoComponent<unknown>,
  [hookCard.kind]: hookCard as VideoComponent<unknown>,
  [outroCard.kind]: outroCard as VideoComponent<unknown>,
  [chapter.kind]: chapter as VideoComponent<unknown>,
};
