# Local typefaces

The application serves these Latin subsets locally so the interface works without a Google Fonts request:

- `manrope-latin-variable.woff2`: Manrope, weights 400-800.
- `instrument-serif-latin.woff2`: Instrument Serif, regular.
- `instrument-serif-latin-italic.woff2`: Instrument Serif, italic.
- `jetbrains-mono-latin-variable.woff2`: JetBrains Mono, weights 400-700.

The font binaries were retrieved from the Google Fonts CSS API on 2026-07-24. Each family is distributed under the SIL Open Font License 1.1. Chinese content uses the operating-system fallback stack defined in `src/styles.css`, avoiding a large bundled CJK font payload.
