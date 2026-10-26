import type { TreatmentDetail } from "./brandDecisions";
export function TreatmentSections({ detail }: { detail?: TreatmentDetail | null }) {
  return <>{detail?.sections.map(section => <div key={section.key} className="treatment-section">
    <h4>{section.title}</h4><p style={{ whiteSpace: "pre-wrap" }}>{section.text}</p>
  </div>)}</>;
}
