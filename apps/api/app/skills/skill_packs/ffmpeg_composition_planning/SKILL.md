---
skill_id: ffmpeg_composition_planning
name: FFmpeg Composition Planning
description: Plan ordered segment composition and export strategy.
---

# Purpose

Guide final video composition after media segments are ready.

# When To Use

Use for final-video-generation-agent and final-composition nodes.

# Inputs

Downloaded video segments, BGM assets, subtitles, watermarks, export settings.

# Output Guidance

Describe ordered concat, fallback transcode, output path, and metadata requirements.

# Prompt Rules

- Compose only after required segments exist locally.
- Preserve segment order.
- Record FFmpeg commands and stderr on failure.

# Do Not

- Do not generate fake final mp4 files.
- Do not use LLM video generation for final composition.
