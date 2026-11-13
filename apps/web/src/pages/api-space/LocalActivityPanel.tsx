import { useEffect, useRef, useState } from "react";
import { v2Api } from "../../api/v2Client.ts";
import type { LocalRuntimeStatisticsV1 } from "../../api/localRuntimeStatistics.ts";
import { useTranslation } from "../../i18n/useTranslation.ts";

export function LocalActivityPanel() {
  const t = useTranslation();
  const [report, setReport] = useState<LocalRuntimeStatisticsV1 | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  const load = async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setError(false);
    try {
      const response = await v2Api.localRuntimeStatistics(controller.signal);
      if (!controller.signal.aborted) setReport(response);
    } catch {
      if (!controller.signal.aborted) setError(true);
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  };

  return (
    <section className="api-space-provider-surface api-space-local-activity" aria-label={t("Local activity")}>
      <div className="api-space-local-activity__heading">
        <h2>{t("Local activity")}</h2>
        <button type="button" className="small-action" disabled={pending} onClick={() => void load()}>
          {t(pending ? "Loading statistics..." : report ? "Refresh statistics" : "Load local activity")}
        </button>
      </div>
      <p className="api-space-model-count">{t("Local execution outcomes from the last 7 days. Results reflect this computer's sample.")}</p>
      {error ? <p role="alert">{t("Local statistics could not be loaded. Try again.")}</p> : null}
      {report ? (
        <>
          <p className="api-space-model-count">
            {t("{count} execution records", { count: report.sampled_members })}
            {" · "}<time dateTime={report.generated_at}>{new Date(report.generated_at).toLocaleString()}</time>
          </p>
          {report.truncated ? <p>{t("Showing the latest 5,000 execution records.")}</p> : null}
          {!report.items.length ? <p>{t("No execution records in the last 7 days.")}</p> : (
            <div className="api-space-local-activity__table">
              <table>
                <thead><tr>
                  <th scope="col">{t("Model")}</th><th scope="col">{t("Succeeded")}</th>
                  <th scope="col">{t("Failed")}</th><th scope="col">{t("Active")}</th>
                  <th scope="col">{t("Cancelled / blocked / skipped")}</th><th scope="col">{t("Success rate")}</th>
                  <th scope="col">{t("Average successful duration")}</th><th scope="col">{t("Failure reasons")}</th>
                </tr></thead>
                <tbody>{report.items.map((item) => (
                  <tr key={item.model_ref ?? "unknown-model"}>
                    <td>{item.model_ref ?? t("Unresolved model")}</td><td>{item.succeeded}</td><td>{item.failed}</td><td>{item.active}</td>
                    <td>{item.cancelled} / {item.blocked} / {item.skipped}</td>
                    <td>{item.success_rate === null ? t("Unknown") : `${Math.round(item.success_rate * 100)}%`}</td>
                    <td>{item.mean_success_seconds === null ? t("Unknown") : t("{seconds}s ({count} samples)", { seconds: item.mean_success_seconds.toFixed(1), count: item.duration_samples })}</td>
                    <td>{Object.entries(item.error_codes).map(([code, count]) => `${code}: ${count}`).join("; ") || "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
          {!report.cost_available ? <p className="api-space-model-count">{t("Provider costs are not reported.")}</p> : null}
        </>
      ) : null}
    </section>
  );
}
