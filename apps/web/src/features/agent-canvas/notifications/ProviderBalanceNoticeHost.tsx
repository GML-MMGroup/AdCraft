import { useSyncExternalStore } from "react";

import { ProviderBalanceDialog } from "./ProviderBalanceDialog.tsx";
import {
  dismissProviderBalanceNotice,
  providerBalanceNoticeSnapshot,
  subscribeProviderBalanceNotice,
} from "./providerBalanceNoticeStore.ts";

/** Renders the single provider balance notice for the whole canvas surface. */
export function ProviderBalanceNoticeHost() {
  const notice = useSyncExternalStore(
    subscribeProviderBalanceNotice,
    providerBalanceNoticeSnapshot,
    providerBalanceNoticeSnapshot,
  );
  if (!notice) return null;
  return <ProviderBalanceDialog notice={notice} onDismiss={dismissProviderBalanceNotice} />;
}
