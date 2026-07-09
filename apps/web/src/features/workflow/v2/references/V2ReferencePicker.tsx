import type { V2ReferenceAttachRequest } from "../../../../types-v2.ts";

type V2ReferencePickerProps = {
  targetType: "item" | "slot";
  targetId: string;
  assets: Array<{ asset_id: string; display_name?: string; media_type?: string }>;
  onAttach: (request: V2ReferenceAttachRequest) => void;
};

export function V2ReferencePicker({ targetType, targetId, assets, onAttach }: V2ReferencePickerProps) {
  return (
    <section className="v2-reference-picker">
      <header>Reference picker</header>
      <p>Frontend sends high-level ids; backend expands reference bundles.</p>
      {assets.map((asset) => (
        <button
          key={asset.asset_id}
          type="button"
          onClick={() =>
            onAttach({
              target_type: targetType,
              target_id: targetId,
              source_asset_id: asset.asset_id,
              reference_kind: "explicit",
            })
          }
        >
          {asset.display_name || asset.asset_id}
        </button>
      ))}
    </section>
  );
}
