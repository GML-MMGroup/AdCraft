import { uiMessages, type MessageValues, type UiMessageKey } from "../../../i18n/uiMessages.ts";

type Translate = (key: UiMessageKey, values?: MessageValues) => string;

// Fixed API prompts may have been stored in either language by an older task.
const translatedKeys = new Map<string, UiMessageKey>(
  Object.entries(uiMessages).map(([key, value]) => [value, key as UiMessageKey]),
);

/** Translate recognized interface copy; leave generated questions and content untouched. */
export function guidedInteractionCopy(text: string, t: Translate): string {
  const key = Object.hasOwn(uiMessages, text) ? text as UiMessageKey : translatedKeys.get(text);
  if (key) return t(key);
  const duration = /^(\d+) seconds$/.exec(text) ?? /^(\d+) 秒$/.exec(text);
  if (duration) return t("{count} seconds", { count: duration[1] });
  const characters = /^(\d+) characters$/.exec(text) ?? /^(\d+) 个角色$/.exec(text);
  if (characters) return t("{count} characters", { count: characters[1] });
  const authorCharacters = /^Author (\d+) characters?\.$/.exec(text) ?? /^设计 (\d+) 个角色。$/.exec(text);
  if (authorCharacters) return t(authorCharacters[1] === "1" ? "Author {count} character." : "Author {count} characters.", { count: authorCharacters[1] });
  const produceDuration = /^Produce a (\d+)-second advertisement\.$/.exec(text) ?? /^制作 (\d+) 秒的广告。$/.exec(text);
  if (produceDuration) return t("Produce a {count}-second advertisement.", { count: produceDuration[1] });
  return text;
}
