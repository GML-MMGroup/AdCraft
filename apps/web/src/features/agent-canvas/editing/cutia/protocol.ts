import type { CutiaMedia, CutiaSnapshot } from "./project.ts";

export const CUTIA_CHANNEL = "adcraft-cutia-v1";
export interface CutiaEnvelope { channel: typeof CUTIA_CHANNEL; session: string; type: string; requestId?: string; [key: string]: unknown }
export type CutiaInit = { snapshot: CutiaSnapshot; language: "en" | "zh" };
export type CutiaUpload = { file: File; mediaId: string };
export type CutiaUploadResult = { media: CutiaMedia };

export function isCutiaMessage(event: MessageEvent, source: Window | null, session: string): event is MessageEvent<CutiaEnvelope> {
  return event.origin === window.location.origin && event.source === source && source !== null
    && event.data?.channel === CUTIA_CHANNEL && event.data.session === session
    && typeof event.data.type === "string";
}
