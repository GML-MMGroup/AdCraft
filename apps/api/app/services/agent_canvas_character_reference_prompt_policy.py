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
CHARACTER_IDENTITY_SCOPE = (
    "Identity facts below do not prescribe the reference pose. Preserve physical identity, "
    "anatomy, proportions, wardrobe and distinguishing details; story actions describe "
    "film performance, not a required pose or camera crop for this reference."
)
CHARACTER_TURNAROUND_FRAMING = (
    "Unless a different crop is explicitly authored for this reference, fit the complete "
    "figure inside each view: scale each complete figure down uniformly when needed, "
    "leaving space above the head and below the feet. Keep the same figure scale and "
    "ground line across all three views. Do not enlarge the face by cutting off the legs "
    "or compressing body proportions. Include the complete silhouette and extremities "
    "for nonhuman characters. Use a neutral reference stance compatible with the "
    "character's anatomy, mobility aids and confirmed physical state. Story actions in "
    "inherited identity descriptions are context; do not reuse a film pose unless "
    "explicitly requested for this reference."
)
CHARACTER_TURNAROUND_RENDERING_AUTHORITY = (
    "Rendering authority: inherit the bound Main's rendering treatment by default. "
    "An explicitly authored rendering change for this Turnaround takes precedence in its "
    "specified regions over inherited or default treatment; keep the Main's treatment elsewhere. "
    "Apply that direction consistently wherever those regions are visible across the three views. "
    "Rendering changes do not alter physical identity, facial structure, hair, wardrobe, "
    "proportions, material identity or physical colors."
)
CHARACTER_TURNAROUND_PROMPT = (
    "Use the bound Character Main image as the sole identity master. Render one turnaround "
    "sheet with exactly three full-body figures arranged left-to-right as "
    "forward-facing, exact side profile, and rear-facing. "
    + DEFAULT_REFERENCE_PRESENTATION
    + " All three views show the same character with identical "
    "features, hair where present, wardrobe, proportions, silhouette, materials and palette. "
    "Preserve original costume printing and authored accessories. "
    + CHARACTER_TURNAROUND_RENDERING_AUTHORITY
    + " "
    + CHARACTER_TURNAROUND_FRAMING
    + " "
    + DEFAULT_IMAGE_OVERLAYS
)


class CharacterReferencePromptPolicy:
    """Compile image layout constraints without overriding the selected medium."""

    policy_id = "adcraft.agent_canvas.character_reference.v5"

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
