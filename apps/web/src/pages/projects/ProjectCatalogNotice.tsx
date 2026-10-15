import { useTranslation } from "../../i18n/useTranslation";
export function ProjectCatalogNotice({
  error,
  refreshing,
  onRetry,
}: {
  error: string | null;
  refreshing: boolean;
  onRetry: () => Promise<boolean>;
}) {
  const t = useTranslation();
  if (!error) return null;
  return (
    <div className="project-catalog-notice" role="status">
      <span>{error}</span>
      <button type="button" className="small-action" disabled={refreshing} onClick={() => void onRetry()}>
        {t(refreshing ? "Refreshing..." : "Retry")}
      </button>
    </div>
  );
}
