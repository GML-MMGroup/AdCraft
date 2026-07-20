---
skill_id: segment_generation_planning
name: Segment Generation Planning
description: Plan formal storyboard video segments and legal per-task durations.
---

# Purpose

Prepare video generation as ordered short segments instead of one large task.

# When To Use

Use for final-video-generation-agent and storyboard-video-generation nodes.

# Inputs

Storyboard scenes, requested duration, aspect ratio, resolution, video model limits.

# Output Guidance

Define segment prompts, order, legal duration, and task submission notes.

# Prompt Rules

- Prefer 10 second segments when possible.
- Use 5 second segments when required by model limits.
- Preserve storyboard order.

# Do Not

- Do not submit 30 or 60 seconds as one Seedance task.
- Do not fake completed video URLs before tasks finish.
