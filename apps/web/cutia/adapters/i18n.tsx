import { useSyncExternalStore } from "react";
import zh from "../../vendor/cutia/locales/zh.json";
import en from "../../vendor/cutia/locales/en.json";

let language = "en";
const listeners = new Set<() => void>();
const translated = Object.fromEntries(Object.entries(en).map(([key, value]) => [value, (zh as Record<string, string>)[key] || value]));
translated["Connection interrupted. Retrying…"] = "连接中断，正在重试…";
Object.assign(translated, { "Unable to download media.": "素材下载失败：", "Media must belong to this project.": "素材必须属于当前项目。", "Media": "素材", "Text": "文字", "Transitions": "转场", "Stickers": "贴纸", "Output settings": "输出设置", "Frame rate": "帧率", "Background color": "背景颜色", "Loading media": "正在加载素材", "Editor tools": "剪辑工具", "Editor panels": "剪辑面板", "Browser export requires a current Chrome or Edge browser over HTTPS.": "浏览器导出需要在 HTTPS 下使用新版 Chrome 或 Edge。" });
export function setLanguage(value: string) { language = value; document.documentElement.lang = value; listeners.forEach((listener) => listener()); }
export function t(key: string, options: Record<string, unknown> = {}): string {
  const dictionary = (language === "zh" ? zh : en) as Record<string, string>;
  const template = dictionary[key] || (language === "zh" ? translated[key] : key) || key;
  return template.replace(/\{\{\s*([^} ]+)\s*\}\}/g, (_, name: string) => String(options[name] ?? ""));
}
const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
export function useTranslation() { useSyncExternalStore(subscribe, () => language); return { t, i18n: { language } }; }
