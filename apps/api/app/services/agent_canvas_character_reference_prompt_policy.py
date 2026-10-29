"""Style-preserving layout policy for Character reference images."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from app.schemas.agent_canvas_ad_media import CharacterDesignAssetContentV2


@dataclass(frozen=True, slots=True)
class CompiledCharacterReferencePolicyV1:
    policy_id: str
    policy_digest: str
    negative_boundary_digest: str
    positive_boundary: str
    negative_boundary: str


CHARACTER_MAIN_PROMPT = (
    "Create one full-body character reference in the selected visual style. Show exactly one "
    "character in a natural standing pose with a slight three-quarter front view on a seamless "
    "light-neutral design background with no environmental objects. Use only a subtle grounding "
    "shadow. Preserve distinctive facial or surface features, hair where present, wardrobe "
    "construction, body proportions, silhouette, materials and color palette."
)
CHARACTER_TURNAROUND_PROMPT = (
    "Use the bound Character Main image as the sole identity master. Render one turnaround "
    "sheet with exactly three unlabeled full-body figures arranged left-to-right as "
    "forward-facing, exact side profile, and rear-facing on a seamless light-neutral design "
    "background. All three views show the same character with identical features, hair where "
    "present, wardrobe, proportions, silhouette, materials, palette, and the same selected "
    "rendering treatment as the bound Main. Keep the sheet blank: no headings, orientation "
    "labels, captions, typography, logos, or watermarks anywhere. Do not reinterpret or "
    "redesign the identity."
)


class CharacterReferencePromptPolicy:
    """Compile image layout constraints without overriding the selected medium."""

    policy_id = "adcraft.agent_canvas.character_reference.v2"

    def compile(
        self,
        content: CharacterDesignAssetContentV2,
    ) -> CompiledCharacterReferencePolicyV1:
        if content.character_asset_kind == "identity_master":
            positive = CHARACTER_MAIN_PROMPT
            negative = (
                "No multiple characters, product placement, environment, action sequence, "
                "environmental object, contact sheet, or turnaround sheet."
            )
        else:
            positive = CHARACTER_TURNAROUND_PROMPT
            negative = (
                "No identity drift, wardrobe change, extra character, extra view, "
                "head panel, detail panel, material panel, action pose, product, scene, label, "
                "heading, orientation label, caption, typography, logo, or watermark."
            )
        digest = sha256(f"{self.policy_id}\n{positive}\n{negative}".encode()).hexdigest()
        return CompiledCharacterReferencePolicyV1(
            policy_id=self.policy_id,
            policy_digest=digest,
            negative_boundary_digest=sha256(negative.encode()).hexdigest(),
            positive_boundary=positive,
            negative_boundary=negative,
        )
