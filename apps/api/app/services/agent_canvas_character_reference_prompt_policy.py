"""Style-preserving layout policy for Character reference images."""

from __future__ import annotations

from app.services.agent_canvas_image_presentation import (
    DEFAULT_REFERENCE_PRESENTATION,
    DEFAULT_IMAGE_OVERLAYS,
)

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
    "Create one full-body character reference in the selected visual style. "
    "Follow the authored pose, expression, accessories and setting. "
    + DEFAULT_REFERENCE_PRESENTATION
    + " Preserve distinctive facial or surface features, "
    "hair where present, wardrobe, body proportions, silhouette, materials and color palette."
)
CHARACTER_TURNAROUND_PROMPT = (
    "Use the bound Character Main image as the sole identity master. Render one turnaround "
    "sheet with exactly three full-body figures arranged left-to-right as "
    "forward-facing, exact side profile, and rear-facing. "
    + DEFAULT_REFERENCE_PRESENTATION
    + " All three views show the same character with identical "
    "features, hair where present, wardrobe, proportions, silhouette, materials, palette, "
    "and the same selected rendering treatment as the bound Main. "
    "Preserve original costume printing and authored accessories. " + DEFAULT_IMAGE_OVERLAYS
)


class CharacterReferencePromptPolicy:
    """Compile image layout constraints without overriding the selected medium."""

    policy_id = "adcraft.agent_canvas.character_reference.v3"

    def compile(
        self,
        content: CharacterDesignAssetContentV2,
    ) -> CompiledCharacterReferencePolicyV1:
        if content.character_asset_kind == "identity_master":
            positive = CHARACTER_MAIN_PROMPT
            negative = DEFAULT_IMAGE_OVERLAYS
        else:
            positive = CHARACTER_TURNAROUND_PROMPT
            negative = "Avoid identity drift between views. " + DEFAULT_IMAGE_OVERLAYS
        digest = sha256(f"{self.policy_id}\n{positive}\n{negative}".encode()).hexdigest()
        return CompiledCharacterReferencePolicyV1(
            policy_id=self.policy_id,
            policy_digest=digest,
            negative_boundary_digest=sha256(negative.encode()).hexdigest(),
            positive_boundary=positive,
            negative_boundary=negative,
        )
