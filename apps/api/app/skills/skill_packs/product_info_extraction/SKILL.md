---
skill_id: product_info_extraction
name: Product Info Extraction
description: Extract product facts, constraints, and usable claims.
---

# Purpose

Turn product descriptions, uploaded asset notes, and user constraints into reliable product facts.

# When To Use

Use for requirements-analysis and product-design nodes.

# Inputs

Product name, product description, selected assets, selling point notes, brand constraints.

# Output Guidance

Summarize facts that downstream strategy, script, and visual nodes can safely reuse.

# Prompt Rules

- Prefer concrete product facts over generic benefits.
- Preserve brand, packaging, color, logo, and shape constraints when present.
- Call out missing or uncertain information instead of inventing it.

# Do Not

- Do not invent unsupported claims.
- Do not turn internal user instructions into audience-facing copy.
