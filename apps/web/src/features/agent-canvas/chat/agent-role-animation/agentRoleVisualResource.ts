import type { AgentCapabilityIdV2 } from "../../../../types-v2.ts";
import { agentRoleBitmapManifest } from "./agentRoleBitmapManifest.ts";
import {
  preloadAgentRoleAnimation, retryAgentRoleAnimation,
  canRetryAgentRoleAnimation,
  type AgentRoleArtworkComponent,
} from "./agentRoleAnimationRegistry.ts";

export type RoleVisualMode = "bitmap" | "animated";
export interface RoleVisualSnapshot {
  status: "pending" | "ready" | "fallback";
  source: string | null;
  Artwork: AgentRoleArtworkComponent | null;
  error: string | null;
  generation: number;
  /** Generic means the UI must draw its code-native marker, never a broken img. */
  fallbackKind: "none" | "bitmap" | "generic";
  retryAvailable?: boolean;
}
interface BitmapAsset { source: string; fallback: string; revision: string }
interface Dependencies {
  asset(role: AgentCapabilityIdV2): BitmapAsset;
  decode(source: string): Promise<HTMLImageElement>;
  load(role: AgentCapabilityIdV2): Promise<AgentRoleArtworkComponent>;
  retryModule(role: AgentCapabilityIdV2): void;
  canRetryModule?(role: AgentCapabilityIdV2): boolean;
}
interface Entry {
  key: string;
  asset: BitmapAsset;
  bitmapStarted: boolean;
  moduleStarted: boolean;
  full: HTMLImageElement | null;
  small: HTMLImageElement | null;
  Artwork: AgentRoleArtworkComponent | null;
  bitmapError: string | null;
  moduleError: string | null;
  expired: Set<RoleVisualMode>;
  timers: Map<RoleVisualMode, ReturnType<typeof setTimeout>>;
  bitmap: RoleVisualSnapshot;
  animated: RoleVisualSnapshot;
}

/** At most one artwork revision per capability; decoding is shared by both modes. */
export function createRoleVisualCache(deps: Dependencies) {
  const entries = new Map<AgentCapabilityIdV2, Entry>();
  const listeners = new Map<AgentCapabilityIdV2, Set<() => void>>();
  const retriedRevision = new Map<AgentCapabilityIdV2, string>();
  let generation = 0;
  const get = (role: AgentCapabilityIdV2): Entry => {
    const asset = deps.asset(role);
    const key = `${role}:${asset.revision}:${asset.source}`;
    const current = entries.get(role);
    if (current?.key === key) return current;
    current?.timers.forEach(clearTimeout);
    const pending: RoleVisualSnapshot = { status: "pending", source: null, Artwork: null, error: null, generation: ++generation, fallbackKind: "none" };
    const entry: Entry = { key, asset, bitmapStarted: false, moduleStarted: false,
      full: null, small: null, Artwork: null, bitmapError: null, moduleError: null,
      expired: new Set(), timers: new Map(), bitmap: pending, animated: pending };
    entries.set(role, entry);
    return entry;
  };
  const notify = (role: AgentCapabilityIdV2) => listeners.get(role)?.forEach(listener => listener());
  const publish = (role: AgentCapabilityIdV2, entry: Entry) => {
    if (entries.get(role) !== entry) return;
    let changed = false;
    for (const mode of ["bitmap", "animated"] as const) {
      const ready = !!entry.full && (mode === "bitmap" || !!entry.Artwork);
      const error = entry.bitmapError ?? (mode === "animated" ? entry.moduleError : null);
      const fallback = !ready && (!!error || entry.expired.has(mode));
      const status = ready ? "ready" : fallback ? "fallback" : "pending";
      const source = status === "pending" ? null : entry.full ? entry.asset.source : entry.small ? entry.asset.fallback : null;
      const Artwork = ready && mode === "animated" ? entry.Artwork : null;
      const previous = entry[mode];
      if (previous.status !== status || previous.source !== source || previous.Artwork !== Artwork || previous.error !== error) {
        entry[mode] = { status, source, Artwork, error, generation: previous.generation,
          fallbackKind: status === "fallback" ? source ? "bitmap" : "generic" : "none",
          retryAvailable: retriedRevision.get(role) !== entry.key
            && !(mode === "animated" && entry.moduleError && deps.canRetryModule?.(role) === false) };
        changed = true;
      }
      if (status !== "pending") {
        clearTimeout(entry.timers.get(mode));
        entry.timers.delete(mode);
      }
    }
    if (changed) notify(role);
  };
  const prepare = (role: AgentCapabilityIdV2, mode: RoleVisualMode): void => {
    const entry = get(role);
    if (entry[mode].status === "pending" && !entry.timers.has(mode)) {
      entry.timers.set(mode, setTimeout(() => {
        entry.expired.add(mode);
        publish(role, entry);
      }, 1500));
    }
    if (!entry.bitmapStarted) {
      entry.bitmapStarted = true;
      void deps.decode(entry.asset.source).then(image => {
        entry.full = image;
        publish(role, entry);
      }, error => {
        entry.bitmapError = String(error);
        publish(role, entry);
      });
      void deps.decode(entry.asset.fallback).then(image => {
        entry.small = image;
        publish(role, entry);
      }, () => {
        // Generic paintable fallback is used when even the bundled bitmap cannot decode.
        publish(role, entry);
      });
    }
    if (mode === "animated" && !entry.moduleStarted) {
      entry.moduleStarted = true;
      void deps.load(role).then(Artwork => {
        entry.Artwork = Artwork;
        publish(role, entry);
      }, error => {
        entry.moduleError = String(error);
        publish(role, entry);
      });
    }
    publish(role, entry);
  };
  return {
    prepare,
    artworkFailed(role: AgentCapabilityIdV2, error: string) {
      const entry = get(role);
      entry.Artwork = null;
      entry.moduleError = error;
      publish(role, entry);
    },
    snapshot: (role: AgentCapabilityIdV2, mode: RoleVisualMode) => get(role)[mode],
    subscribe(role: AgentCapabilityIdV2, _mode: RoleVisualMode, listener: () => void) {
      let set = listeners.get(role);
      if (!set) { set = new Set(); listeners.set(role, set); }
      set.add(listener);
      return () => { set.delete(listener); if (!set.size) listeners.delete(role); };
    },
    retry(role: AgentCapabilityIdV2, mode: RoleVisualMode) {
      const old = entries.get(role);
      if (old?.[mode].retryAvailable === false) return;
      if (old) retriedRevision.set(role, old.key);
      old?.timers.forEach(clearTimeout);
      entries.delete(role);
      const entry = get(role);
      if (old) {
        entry.full = old.full;
        entry.small = old.small;
        entry.bitmapStarted = !!old.full;
        entry.Artwork = old.Artwork;
        entry.moduleStarted = !!old.Artwork;
      }
      if (!entry.Artwork) deps.retryModule(role);
      if (old?.bitmapStarted) prepare(role, "bitmap");
      if (old?.moduleStarted) prepare(role, "animated");
      prepare(role, mode);
      notify(role);
    },
  };
}

function decodeBitmap(source: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => {
      void (typeof image.decode === "function" ? image.decode() : Promise.resolve()).then(() => {
        if (image.naturalWidth > 0) resolve(image);
        else reject(new Error("Role bitmap has no pixels"));
      }, reject);
    };
    image.onerror = () => reject(new Error("Role bitmap could not be loaded"));
    image.src = source;
  });
}
const cache = createRoleVisualCache({
  asset: role => agentRoleBitmapManifest[role], decode: decodeBitmap,
  load: preloadAgentRoleAnimation, retryModule: retryAgentRoleAnimation,
  canRetryModule: canRetryAgentRoleAnimation,
});
export const prepareRoleVisual = cache.prepare;
export const getRoleVisualSnapshot = cache.snapshot;
export const subscribeRoleVisual = cache.subscribe;
export const retryRoleVisual = cache.retry;
export const reportRoleArtworkError = cache.artworkFailed;
