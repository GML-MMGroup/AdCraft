import { useLocale } from "../i18n/locale.tsx";

export function LanguageSwitcher() {
  const { locale, setLocale } = useLocale();
  const chinese = locale === "zh-CN";

  return (
    <div className="language-switcher-control">
    <div
      className={`language-switcher${chinese ? " is-chinese" : " is-english"}`}
      role="group"
      aria-label={chinese ? "语言：中文" : "Language: English"}
    >
      <span className="language-switcher__thumb" aria-hidden="true" />
      <button
        type="button"
        className="language-switcher__option"
        aria-label="切换到中文"
        aria-pressed={chinese}
        disabled={chinese}
        onClick={() => setLocale("zh-CN")}
      >
        中
      </button>
      <button
        type="button"
        className="language-switcher__option"
        aria-label="Switch to English"
        aria-pressed={!chinese}
        disabled={!chinese}
        onClick={() => setLocale("en-US")}
      >
        EN
      </button>
    </div>
    </div>
  );
}
