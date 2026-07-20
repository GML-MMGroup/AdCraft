from agno.agent import Agent
from agno.models.openai import OpenAIChat

from app.core.config import Settings
from app.core.llm import build_llm_chat_model


def _build_model(settings: Settings | None, model_id: str) -> OpenAIChat | None:
    return build_llm_chat_model(settings, model_id) if settings else None


def build_product_analyst_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=_build_model(settings, settings.llm_requirements_model if settings else ""),
        name="Product Analyst Agent",
        role="Product positioning analyst",
        description="Extracts the product value proposition and audience needs.",
        instructions=[
            "Identify the strongest product benefits.",
            "Summarize the target audience pain points.",
            "Return concise inputs for an advertising campaign.",
        ],
        expected_output="A structured product and audience analysis.",
        telemetry=False,
    )


def build_product_designer_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=_build_model(settings, settings.llm_product_design_model if settings else ""),
        name="Product Designer Agent",
        role="Commercial product designer",
        description="Turns product value into a marketable product presentation strategy.",
        instructions=[
            "Translate the core selling point into a product showcase plan.",
            "Define product presentation details that support commercialization.",
            "Keep the design aligned with the audience, channel, and campaign goal.",
        ],
        expected_output="A structured commercial product design brief.",
        telemetry=False,
    )


def build_creative_director_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=_build_model(settings, settings.llm_creative_model if settings else ""),
        name="Creative Director Agent",
        role="Advertising short-film creative director",
        description="Coordinates the creative flow and turns requirements into a campaign concept.",
        instructions=[
            "Propose one clear creative concept.",
            "Keep the concept aligned with the campaign goal and channels.",
            "Describe the key message and tone.",
            "Coordinate script, visual, and audiovisual handoffs.",
        ],
        expected_output="A structured creative direction.",
        telemetry=False,
    )


def build_script_writer_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=_build_model(settings, settings.llm_script_model if settings else ""),
        name="Script Writer Agent",
        role="Short-form advertising script writer",
        description="Writes a compact ad script from the approved creative direction.",
        instructions=[
            "Write a hook, body, and call to action.",
            "For 15-60 second ads, create 4-6 ordered shot_beats.",
            "Each shot beat must include order, duration_seconds, scene_intent, location_hint, "
            "visual_action, product_action, and spoken_or_on_screen_text.",
            "Keep the copy suitable for the requested channels.",
            "Use product claims supported by the supplied description.",
            "Include subtitle_lines containing only audience-facing spoken or on-screen ad copy.",
            "Do not place user requests, internal briefs, or raw product descriptions in subtitle_lines.",
        ],
        expected_output="A structured short-form advertising script.",
        telemetry=False,
    )


def build_character_designer_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=_build_model(settings, settings.llm_character_model if settings else ""),
        name="Character Designer Agent",
        role="Advertising short-film character designer",
        description="Designs character appearance, personality, and visual identity.",
        instructions=[
            "Define the main character's appearance and personality.",
            "Keep the character aligned with the target audience and campaign tone.",
            "Provide concise visual references for storyboard planning.",
        ],
        expected_output="A structured character design brief.",
        telemetry=False,
    )


def build_scene_designer_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=_build_model(settings, settings.llm_scene_model if settings else ""),
        name="Scene Designer Agent",
        role="Advertising short-film scene designer",
        description="Designs scene layout, lighting, and environmental atmosphere.",
        instructions=[
            "Define multiple key locations and visual atmospheres from the script shot_beats.",
            "For a 30 second ad, provide at least 3 distinct scene specs unless the script explicitly uses one location.",
            "Give every scene a stable scene_id such as scene-reference-1.",
            "Differentiate locations by spatial layout, lighting, atmosphere, and product placement.",
            "Describe lighting and environmental details for each scene.",
            "Keep the scene design practical for storyboard planning.",
        ],
        expected_output="A structured scene design brief.",
        telemetry=False,
    )


def build_storyboard_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=_build_model(settings, settings.llm_storyboard_model if settings else ""),
        name="Storyboard Agent",
        role="Advertising storyboard planner",
        description="Maps the ad script into a simple visual sequence.",
        instructions=[
            "Create a concise ordered visual sequence with one storyboard scene per single keyframe shot.",
            "Match each scene to the script progression.",
            "Every storyboard scene must include order, shot, visual, duration_seconds, camera, action, scene_id, and input_asset_ids.",
            "Bind scene_id to a scene-reference-N and include only the product, scene, and character asset ids needed by that shot.",
            "Do not describe storyboard sheets, multi-panel pages, comic strips, collages, grids, or multiple frames in one scene.",
            "Include useful on-screen text suggestions.",
        ],
        expected_output="A structured scene-by-scene storyboard.",
        telemetry=False,
    )


def build_sound_effects_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=_build_model(settings, settings.llm_sound_effects_model if settings else ""),
        name="Sound Effects Agent",
        role="Advertising sound effects designer",
        description=(
            "Plans only environmental, action, object, transition, and product interaction sounds."
        ),
        instructions=[
            "Create only sound effects for storyboard scenes.",
            "Do not create voices, narration, dubbing, or background music.",
            "Align every sound effect track to the storyboard scene order and timing.",
            "Return generation prompts that can be passed to a sound-effect generator.",
        ],
        expected_output="A structured sound-effects plan.",
        telemetry=False,
    )


def build_voiceover_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=_build_model(settings, settings.llm_voiceover_model if settings else ""),
        name="Voiceover / Dubbing Agent",
        role="Advertising voiceover and dubbing planner",
        description="Plans only human voice, narration, and dubbing based on subtitle cues.",
        instructions=[
            "Use the subtitle plan as the source of truth for voice text and timing.",
            "Do not rewrite subtitle text.",
            "Do not create background music or environmental/action/transition sound effects.",
            "Use character design only to choose voice profiles and emotions.",
            "Return generation prompts for voice tracks aligned to subtitle cues.",
        ],
        expected_output="A structured voiceover and dubbing plan.",
        telemetry=False,
    )


def build_bgm_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=_build_model(settings, settings.llm_bgm_model if settings else ""),
        name="BGM Agent",
        role="Advertising background music planner",
        description="Plans only whole-ad background music based on campaign style and rhythm.",
        instructions=[
            "Create only background music for the full advertisement.",
            "Do not create voices, narration, dubbing, or sound effects.",
            "Base the music on style, emotion, audience, duration, channels, script, and storyboard rhythm.",
            "Return one coherent background music generation prompt and sync notes.",
        ],
        expected_output="A structured background music plan.",
        telemetry=False,
    )


def build_final_video_generation_agent(settings: Settings | None = None) -> Agent:
    return Agent(
        model=_build_model(settings, settings.llm_final_video_model if settings else ""),
        name="Final Video Generation Agent",
        role="Multimodal final advertising video prompt planner",
        description=(
            "Builds the final multimodal prompt package used by the video generation provider."
        ),
        instructions=[
            "Use requirements, creative direction, script, storyboard, character design, scene design, "
            "storyboard images, and selected user assets.",
            "Organize the output as a video-generation-ready multimodal prompt, not a generic plan.",
            "Reference input image or video assets by asset_id and local_path or url.",
            "Keep character, scene, style, camera motion, and continuity instructions explicit.",
            "Do not replace sound-effects, voiceover, or BGM agents; set audio_strategy for the current video model path.",
        ],
        expected_output="A structured multimodal final video generation prompt.",
        telemetry=False,
    )
