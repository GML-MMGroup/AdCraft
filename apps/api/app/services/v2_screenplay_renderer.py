from __future__ import annotations

from app.schemas.workflow_v2_screenplay import V2ScriptPlanV2


_LABELS = {
    "en": {"scene": "Scene", "shot": "Shot", "narration": "Narration"},
    "zh": {"scene": "场景", "shot": "镜头", "narration": "旁白"},
}


class V2ScreenplayRenderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class V2ScreenplayRenderer:
    def render(self, plan: V2ScriptPlanV2) -> str:
        labels = _labels_for_language(plan.language)
        character_names = {
            character.character_id: character.display_name for character in plan.characters
        }
        blocks = [plan.script_title]
        for scene_index, scene in enumerate(plan.scenes, start=1):
            blocks.append(f"{labels['scene']} {scene_index}: {scene.title}\n{scene.description}")
            for shot in (item for item in plan.shots if item.scene_id == scene.scene_id):
                blocks.append(f"{labels['shot']} {shot.shot_index}\n{shot.description}")
                for line in shot.dialogue:
                    speaker = character_names[line.character_id]
                    cue = f" ({line.performance_cue})" if line.performance_cue else ""
                    blocks.append(f'{speaker}{cue}: "{line.text}"')
                if shot.narration is not None:
                    blocks.append(f'{labels["narration"]}: "{shot.narration}"')
        return "\n\n".join(blocks)

    def rendered_plan(self, plan: V2ScriptPlanV2) -> V2ScriptPlanV2:
        return plan.model_copy(update={"script_text": self.render(plan)}, deep=True)

    def validate_canonical_text(self, plan: V2ScriptPlanV2) -> None:
        if plan.script_text != self.render(plan):
            raise V2ScreenplayRenderError(
                "script_version_corrupt",
                "Persisted screenplay text does not match its structured content.",
            )


def _labels_for_language(language: str) -> dict[str, str]:
    normalized = language.strip().lower().replace("_", "-")
    base = normalized.split("-", 1)[0]
    return _LABELS.get(base, _LABELS["en"])
