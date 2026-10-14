import { useCallback } from "react";
import { useUiLocale } from "./locale";
import { translateUi, type MessageValues, type UiMessageKey } from "./uiMessages";

export function useTranslation(fallback = "zh-CN") {
  const locale = useUiLocale(fallback);
  return useCallback((key: UiMessageKey, values?: MessageValues) => translateUi(locale, key, values), [locale]);
}
