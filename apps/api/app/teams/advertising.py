from agno.team import Team

from app.agents.advertising import (
    build_bgm_agent,
    build_character_designer_agent,
    build_creative_director_agent,
    build_final_video_generation_agent,
    build_product_analyst_agent,
    build_product_designer_agent,
    build_scene_designer_agent,
    build_script_writer_agent,
    build_sound_effects_agent,
    build_storyboard_agent,
    build_voiceover_agent,
)
from app.core.config import Settings
from app.core.llm import build_llm_chat_model


def build_advertising_team(settings: Settings | None = None) -> Team:
    return Team(
        model=build_llm_chat_model(settings, settings.llm_team_model) if settings else None,
        name="AdCraft Creative Team",
        role="Coordinates an end-to-end advertising workflow.",
        members=[
            build_product_analyst_agent(settings),
            build_product_designer_agent(settings),
            build_creative_director_agent(settings),
            build_script_writer_agent(settings),
            build_character_designer_agent(settings),
            build_scene_designer_agent(settings),
            build_storyboard_agent(settings),
            build_sound_effects_agent(settings),
            build_voiceover_agent(settings),
            build_bgm_agent(settings),
            build_final_video_generation_agent(settings),
        ],
        instructions=[
            "Move through requirements, commercial product design, script planning, "
            "visual design, audiovisual production, and final composition.",
            "Keep each handoff structured so a frontend can render the workflow.",
        ],
        expected_output="A structured advertising workflow ready for frontend rendering.",
        telemetry=False,
    )
