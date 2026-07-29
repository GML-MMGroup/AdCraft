# Local typefaces

The application serves these Latin subsets locally so the interface works without a Google Fonts request:

- `manrope-latin-variable.woff2`: Manrope, weights 400-800.
- `instrument-serif-latin.woff2`: Instrument Serif, regular.
- `instrument-serif-latin-italic.woff2`: Instrument Serif, italic.
- `jetbrains-mono-latin-variable.woff2`: JetBrains Mono, weights 400-700.
- `space-grotesk-latin-variable.woff2`: Space Grotesk, weights 400-700 in the homepage stylesheet.
- `inter-latin-variable.woff2`: Inter, weights 400-800.
- `clash-display-bold.woff2`: Clash Display, bold.

The Google Fonts binaries were retrieved from the Google Fonts CSS API. Clash Display was retrieved from Fontshare and is distributed under the ITF Free Font License. Chinese content uses the operating-system fallback stacks defined by the relevant page styles, avoiding a large bundled CJK font payload.
