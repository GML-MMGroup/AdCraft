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
- For product_main, product_multiview, prop, character_main, character_turnaround, and scene_board, describe only what a camera can see: physical form, materials, finish, colors, marks, wardrobe, spaces, and lighting. Do not write audience, platform, aspect ratio, price band, positioning, selling-point slogans, usage benefits, brand personality, emotional arcs, or what later shots will use the image for; express brand tone only through visual choices.
- For prop, describe the prop in isolation. Do not mention the hero product, other props, characters, the desk or scene, or where the prop is placed.
- Do not state technical specifications (color temperature, wattage, dimensions, materials grades, certifications) unless the confirmed Brand or user facts state them.
- Do not describe the overall visual style in editable_prompt; the engine appends the confirmed Visual style once.
- For character_main and character_turnaround, depict exactly one outfit. When the confirmed Treatment lists several wardrobes, use only the first listed wardrobe and do not mention the others. Use a calm, natural expression and do not describe performance changes.
- For character_main and character_turnaround, the sheet is always a full-body, head-to-toe identity reference. Ignore any shot framing, crop, or camera distance from the Treatment, such as upper-body, close-up, or partial-body boundaries; those apply only to Storyboard and Video. Describe the wardrobe from head to toe, including top, bottoms, and footwear. When the Treatment names only some garments, complete the rest with plain, understated items in the confirmed palette, without logos or text.
- For product_multiview, copy identity, geometry, materials, marks, and palette from the bound Product Main. Do not add features, controls, screens, ports, or marks that Product Main does not describe.
- For storyboard_grid, describe only the visual frame of each panel. Never request captions, subtitles, slogans, or any on-screen text inside panels, even when the Treatment specifies on-screen text; on-screen text belongs to Editing. Never invent copy.
- For video_segment, the clip is rendered without music; music is authored only by the BGM node. Never mention background music, BGM, soundtrack, music, beats, drops, or cutting to music in any field. Express rhythm only as visual timing, such as a hard cut at 3 s or a freeze frame at 15 s. Sound effects caused by visible actions are allowed.
- Treat explicit user constraints and internal role rules as authoritative over Style advice.
- Never copy sibling prompts, use unbound Assets, invoke another capability, or emit provider, credential, persistence, Node, Binding, or execution controls.
