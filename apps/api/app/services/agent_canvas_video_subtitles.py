"""Apply the frozen Video Node subtitle choice at provider delivery."""

from __future__ import annotations

from collections.abc import Mapping


def apply_video_subtitle_control(prompt: str, parameters: Mapping[str, object]) -> str:
    """Keep saved creative text intact while applying the current explicit control."""

    instruction = (
        "Generate subtitles in the video using white text with a black outline, "
        "no background box, band, or fill behind the text, and a normal readable subtitle size "
        "proportional to the frame. Place them at the lower center within safe margins. "
        "Use the approved dialogue, voiceover, or explicitly authored subtitle text in its "
        "original language, synchronized to the corresponding speech or authored timing. "
        "Subtitles accompany speech; do not replace it or change the audio setting. "
        "Do not invent dialogue or captions for passages without approved subtitle content."
        if parameters.get("generate_subtitles", True) is True
        else "Do not generate subtitles or dialogue/voiceover caption overlays in this video. "
        "Keep the approved speech and audio setting unchanged. This does not remove "
        "product labels, environmental signage, or separately authored brand titles and end cards."
    )
    return (
        f"{prompt}\n\nVideo subtitle control (authoritative for subtitles; overrides conflicting "
        f"subtitle instructions in earlier prompt text or references):\n{instruction}"
    )
