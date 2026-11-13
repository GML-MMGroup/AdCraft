import type { MessageValues, UiMessageKey } from "../../../i18n/uiMessages.ts";
import { guidedInteractionCopy } from "./guidedInteractionCopy.ts";

type Translate = (key: UiMessageKey, values?: MessageValues) => string;

/** Translate fixed API/helper copy while preserving custom prompts, filenames and diagnostics. */
const genericSourceMessages = {
  "This Product source is already selected.": "This image is already selected.",
  "The Product source could not be prepared.": "The selected images could not be prepared.",
  "Unable to prepare the Product source.": "Unable to prepare the selected images.",
} as const;

export function productSourceCopy(text: string, t: Translate, genericSource = false): string {
  const genericKey = genericSourceMessages[text as keyof typeof genericSourceMessages];
  if (genericSource && genericKey) return t(genericKey);
  const maxCount = /^You can select at most (\d+) Product (sources?)\.$/.exec(text);
  if (maxCount) {
    return t(maxCount[2] === "source"
      ? "You can select at most {count} Product source."
      : "You can select at most {count} Product sources.", { count: maxCount[1] });
  }
  return guidedInteractionCopy(text, t);
}
