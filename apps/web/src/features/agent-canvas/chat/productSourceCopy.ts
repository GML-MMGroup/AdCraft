import type { MessageValues, UiMessageKey } from "../../../i18n/uiMessages.ts";
import { guidedInteractionCopy } from "./guidedInteractionCopy.ts";

type Translate = (key: UiMessageKey, values?: MessageValues) => string;

/** Translate fixed API/helper copy while preserving custom prompts, filenames and diagnostics. */
export function productSourceCopy(text: string, t: Translate): string {
  const maxCount = /^You can select at most (\d+) Product (sources?)\.$/.exec(text);
  if (maxCount) {
    return t(maxCount[2] === "source"
      ? "You can select at most {count} Product source."
      : "You can select at most {count} Product sources.", { count: maxCount[1] });
  }
  return guidedInteractionCopy(text, t);
}
