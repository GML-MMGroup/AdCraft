"""Apply the frozen Video Node subtitle choice at provider delivery."""

from __future__ import annotations

from collections.abc import Mapping


_SUBTITLE_BLOCK_START = (
    "Video subtitle control (authoritative for subtitles; overrides conflicting "
    "subtitle instructions in earlier prompt text or references):\n"
)
_SUBTITLE_BLOCK_END = "[End video subtitle control]"
_SUBTITLE_BLOCK_BEGIN = "[Begin video subtitle settings]\n"


_SUBTITLE_ENABLED = (
    "Generate subtitles in the video using white text with a black outline, "
    "no background box, band, or fill behind the text, and a normal readable subtitle size "
    "proportional to the frame. Place them at the lower center within safe margins. "
    "Use the approved dialogue, voiceover, or explicitly authored subtitle text in its "
    "original language, synchronized to the corresponding speech or authored timing. "
    "Subtitles accompany speech; do not replace it or change the audio setting. "
    "Do not invent dialogue or captions for passages without approved subtitle content."
)
_SUBTITLE_DISABLED = (
    "Do not generate subtitles or dialogue/voiceover caption overlays in this video. "
    "Keep the approved speech and audio setting unchanged. This does not remove "
    "product labels, environmental signage, or separately authored brand titles and end cards."
)


def without_managed_video_subtitles(prompt: str) -> str:
    """Remove only complete engine-owned blocks, never interpret authored prose."""
    while _SUBTITLE_BLOCK_BEGIN in prompt:
        before, _, remainder = prompt.partition(_SUBTITLE_BLOCK_BEGIN)
        _, end, after = remainder.partition(_SUBTITLE_BLOCK_END)
        if not end:
            break
        prompt = before.rstrip() + ("\n\n" + after.lstrip() if after.strip() else "")
    for instruction in (_SUBTITLE_ENABLED, _SUBTITLE_DISABLED):
        # Historical engine footers have no delimiters. Match their complete,
        # exact text instead of treating later user prose as part of the footer.
        prompt = prompt.replace(f"{_SUBTITLE_BLOCK_START}{instruction}", "")
    return prompt.rstrip()


def apply_video_subtitle_control(prompt: str, parameters: Mapping[str, object]) -> str:
    """Compile one subtitle choice, preserving the historical provider wire format."""
    instruction = (
        _SUBTITLE_ENABLED
        if parameters.get("generate_subtitles", True) is True
        else _SUBTITLE_DISABLED
    )
    return f"{without_managed_video_subtitles(prompt)}\n\n{_SUBTITLE_BLOCK_START}{instruction}"


def with_managed_video_subtitles(prompt: str, parameters: Mapping[str, object]) -> str:
    """Keep the visible managed section replaceable even when more prose follows."""
    delivered = apply_video_subtitle_control(prompt, parameters)
    body, _, instruction = delivered.rpartition(_SUBTITLE_BLOCK_START)
    return (
        f"{body}{_SUBTITLE_BLOCK_BEGIN}{_SUBTITLE_BLOCK_START}{instruction}\n{_SUBTITLE_BLOCK_END}"
    )
