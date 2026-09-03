---
name: video_agent_role_prompt_authoring
description: Author one strict role-specific creative brief from bounded Agent Canvas authority.
---

# Role Prompt Authoring

Return only the concrete brief variant requested by the current role context.

- Use the selected direction, current requirement/document revisions, and explicit Binding snapshots supplied in the context.
- Keep identity, composition, narrative, sound, and layout details inside the current role's schema.
- For character_turnaround, copy every protected field from character_identity_projection exactly. Do not paraphrase, summarize, translate, or enrich identity, face and hair, silhouette and proportions, wardrobe, accessories, rendering mode, or gender presentation. Describe only the requested turnaround presentation in editable_prompt; editable_prompt cannot replace or override those protected fields.
- Treat explicit user constraints and internal role rules as authoritative over Style advice.
- Never copy sibling prompts, use unbound Assets, invoke another capability, or emit provider, credential, persistence, Node, Binding, or execution controls.
