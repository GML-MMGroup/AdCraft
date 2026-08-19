"""Provider-boundary rendering policy for human Character reference images."""

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


class CharacterReferencePromptPolicy:
    """Compile fixed image-only Character medium and layout constraints."""

    policy_id = "adcraft.agent_canvas.character_reference.v1"

    def compile(
        self,
        content: CharacterDesignAssetContentV2,
    ) -> CompiledCharacterReferencePolicyV1:
        if content.character_asset_kind == "identity_master":
            positive = (
                "Create one detailed semi-realistic 2D commercial character illustration, "
                "clearly illustrated rather than photographed. Show exactly one full-body "
                "human in a natural standing pose with a slight three-quarter front view on "
                "a seamless light-neutral design background with no environmental objects. "
                "Use only a subtle grounding shadow. Preserve readable facial features, hair, "
                "wardrobe construction, body proportions, silhouette, and color palette. "
                "Any photographic or live-action campaign direction applies only to eventual "
                "Video output, not this Character reference image."
            )
            negative = (
                "No photographic portrait, photorealistic skin, live-action capture, real-person "
                "likeness, multiple people, product placement, environment, action sequence, "
                "environmental object, contact sheet, or turnaround sheet."
            )
        else:
            positive = (
                "Use the bound Character Main image as the sole identity master. Render one "
                "turnaround sheet with exactly three unlabeled full-body figures arranged "
                "left-to-right as forward-facing, exact side profile, and rear-facing on a "
                "seamless light-neutral design background. All three views are the same person "
                "with identical face, hair, "
                "wardrobe, proportions, silhouette, materials, palette, and detailed "
                "semi-realistic illustration treatment, clearly illustrated rather than "
                "photographed. Keep the sheet blank: no headings, orientation labels, captions, "
                "typography, logos, or watermarks anywhere. Do not reinterpret or redesign the "
                "identity. Any photographic or live-action campaign direction applies only to "
                "eventual Video output, not this Character reference image."
            )
            negative = (
                "No photographic rendering, photography, live-action capture, identity drift, "
                "wardrobe change, extra person, extra view, "
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
