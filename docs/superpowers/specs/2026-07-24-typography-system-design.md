# Typography System Design

**Date:** 2026-07-24

## Goal

Replace the current Geist and Bodoni Moda pairing with a locally served type
system that suits AdCraft as a creative production tool: Manrope for interface
work, Instrument Serif for the Home brand moment, Noto Sans SC and system CJK
fallbacks for Chinese, and JetBrains Mono for technical identifiers.

## Scope

- Serve Manrope, Instrument Serif, and JetBrains Mono WOFF2 files from
  `apps/web/public/fonts/`; the application must not depend on Google Fonts at
  runtime.
- Define one set of explicit font tokens for interface, brand/editorial,
  Chinese fallback, and monospace text.
- Use Manrope across application surfaces, headings, controls, and workflow
  content.
- Limit Instrument Serif to the Home product hero title and its accent.
- Use JetBrains Mono only for API keys, model identifiers, and other technical
  code-like values.
- Normalize the global font weight scale to 400, 500, 600, 700, and 800.
- Reduce oversized operational page and section headings while preserving the
  Home hero as the only expressive large-scale display composition.
- Preserve the current layout, colors, interaction behavior, asset media, and
  page structure.

## Non-Goals

- Do not add a localization system or translate product copy.
- Do not bundle the complete Noto Sans SC glyph set. The stack prefers a locally
  installed Noto Sans SC and then OS CJK fonts, avoiding a large static asset
  payload for a primarily English interface.
- Do not redesign individual page layouts or alter workflow behavior.

## Font Roles

| Role | Font stack | Use |
| --- | --- | --- |
| Interface | Manrope, Noto Sans SC, PingFang SC, Microsoft YaHei, sans-serif | Default body, navigation, forms, buttons, cards, workbench |
| Brand | Instrument Serif, Songti SC, serif | Home product hero only |
| Technical | JetBrains Mono, SFMono-Regular, Cascadia Code, monospace | API key status, model IDs, opaque identifiers |

## Typography Rules

- Body text uses weight 400; supporting labels use 500; controls use 600;
  compact headings use 700; display emphasis uses 800 only where necessary.
- Operational page titles use a 40-48px desktop range and 32-36px mobile
  range. Section titles use a 32-40px desktop range.
- Home remains the only hero surface using Instrument Serif; its desktop title
  is 68px and scales down without changing the text hierarchy.
- Inline technical values use the technical token rather than inheriting the
  interface font.
- No style may use synthetic weights above 800 or arbitrary values such as 750,
  850, 900, or 950.

## Loading and Fallback

- `index.html` removes the Google Fonts preconnect and stylesheet links.
- `styles.css` declares local `@font-face` rules with `font-display: swap` for
  the four WOFF2 assets.
- The local Latin font files cover the English-first interface. Chinese uses the
  ordered system fallback stack when Noto Sans SC is not installed.
- Font loading failure must leave every screen readable with the final generic
  family fallback.

## Verification

- Add a typography contract test that checks local font asset references,
  token ownership, removal of external Google Fonts, approved weight values,
  and the Home/operational heading scales.
- Run the existing frontend tests, React lint, and production build.
- Inspect Home, Assets, API Space, and Workflow at desktop and mobile widths;
  verify font files load locally, titles do not clip, controls remain stable,
  and technical values use the mono face.
