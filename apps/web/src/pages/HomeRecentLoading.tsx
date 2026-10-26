import { useTranslation } from "../i18n/useTranslation";
export function HomeRecentLoading() {
  const t = useTranslation();
  return (
    <div className="recent-strip home-recent-loading" role="status" aria-label={t("Loading recent projects")}>
      <span className="home-recent-loading__label">{t("Loading recent projects...")}</span>
      {[0, 1, 2, 3].map((index) => <div key={index} className="recent-card recent-card--skeleton" aria-hidden="true" />)}
    </div>
  );
}
