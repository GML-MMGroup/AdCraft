import { useEffect, useRef, useState } from "react";
import { agentCanvasApi, isV2ApiError } from "../api/agentCanvasApi.ts";
import { localeChangedEventName, useLocale, type AppLocale } from "../i18n/locale.tsx";
import type { GuidedSessionStateV2 } from "../types-v2.ts";

export function LanguageSwitcher({ workflowId }: { workflowId?: string | null }) {
  const { locale, setLocale } = useLocale();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);
  const busyRef = useRef(false);
  const chinese = locale === "zh-CN";
  useEffect(() => {
    generationRef.current += 1;
    busyRef.current = false;
    setPending(false);
    setError(null);
    return () => { generationRef.current += 1; };
  }, [workflowId]);

  async function changeLocale(next: AppLocale) {
    if (next === locale || busyRef.current) return;
    const generation = generationRef.current;
    busyRef.current = true;
    setPending(true);
    setError(null);
    try {
      let updatedSession: GuidedSessionStateV2 | undefined;
      if (workflowId) {
        let session;
        try {
          session = await agentCanvasApi.agentCanvasCreativeSession(workflowId);
        } catch (cause) {
          // A project without a session uses the preference on its first chat turn.
          if (!isV2ApiError(cause) || cause.status !== 404) throw cause;
        }
        if (generation !== generationRef.current) return;
        if (session) {
          updatedSession = await agentCanvasApi.updateAgentCanvasCreativeSessionLocale(workflowId, {
            expected_revision: session.revision,
            response_locale: next,
          });
        }
      }
      if (generation !== generationRef.current) return;
      setLocale(next);
      if (workflowId) window.dispatchEvent(new CustomEvent(localeChangedEventName, {
        detail: { workflowId, locale: next, session: updatedSession },
      }));
    } catch (cause) {
      if (generation !== generationRef.current) return;
      setError(isV2ApiError(cause) && cause.status === 409
        ? (chinese ? "项目已更新，请再次点击切换语言。" : "The project changed. Click again to switch language.")
        : (chinese ? "语言切换失败，请重试。" : "Language could not be changed. Please retry."));
    } finally {
      if (generation === generationRef.current) {
        busyRef.current = false;
        setPending(false);
      }
    }
  }

  return (
    <div className="language-switcher-control">
    <div
      className={`language-switcher${chinese ? " is-chinese" : " is-english"}`}
      role="group"
      aria-label={chinese ? "语言：中文" : "Language: English"}
      aria-busy={pending}
    >
      <span className="language-switcher__thumb" aria-hidden="true" />
      <button
        type="button"
        className="language-switcher__option"
        aria-label="切换到中文"
        aria-pressed={chinese}
        disabled={pending || chinese}
        onClick={() => void changeLocale("zh-CN")}
      >
        中
      </button>
      <button
        type="button"
        className="language-switcher__option"
        aria-label="Switch to English"
        aria-pressed={!chinese}
        disabled={pending || !chinese}
        onClick={() => void changeLocale("en-US")}
      >
        EN
      </button>
    </div>
    {error ? <span className="language-switcher-error" role="alert">{error}</span> : null}
    </div>
  );
}
