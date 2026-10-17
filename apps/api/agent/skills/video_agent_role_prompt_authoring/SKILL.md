---
name: video_agent_role_prompt_authoring
description: Author one strict role-specific creative brief from bounded Agent Canvas authority.
---

# Role Prompt Authoring

Return only the concrete brief variant requested by the current role context.

- Use the selected direction, current requirement/document revisions, and explicit Binding snapshots supplied in the context.
- Keep identity, composition, narrative, sound, and layout details inside the current role's schema.
- For character_turnaround, copy every protected field from character_identity_projection exactly. Do not paraphrase, summarize, translate, or enrich identity, face and hair, silhouette and proportions, wardrobe, accessories, rendering mode, or gender presentation. Describe only the requested turnaround presentation in editable_prompt; editable_prompt cannot replace or override those protected fields.
- For scene_board, use only the typed Scene environment projection, Scene-specific style, valid Scene references, technical constraints, and structural exclusions. Preserve lighting, materials, palette, composition, atmosphere, and reference fidelity. Do not introduce positive Character, Product, Prop, or narrative progression content. Explicit exclusions such as no characters or props remain valid.
- For product_main, product_multiview, and prop, describe only what a camera can see: physical form, materials, finish, colors, marks, and lighting on the object. Do not write audience, price band, positioning, selling-point slogans, usage benefits, or brand personality as text in these briefs; express brand tone only through visual choices.
- For prop, describe the prop in isolation. Do not mention the hero product, other props, characters, the desk or scene, or where the prop is placed.
- Do not state technical specifications (color temperature, wattage, dimensions, materials grades, certifications) unless the confirmed Brand or user facts state them.
- Write the style once. Do not restate the Visual style inside the body.
- Treat explicit user constraints and internal role rules as authoritative over Style advice.
- Never copy sibling prompts, use unbound Assets, invoke another capability, or emit provider, credential, persistence, Node, Binding, or execution controls.
