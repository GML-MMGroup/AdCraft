export type FontSource = "local" | "system" | "web";

export type FontCollection =
  | "handwritten-signature"
  | "handwritten-casual"
  | "handwritten-marker"
  | "handwritten-playful";

export type TypographyRegionId =
  | "heroMain"
  | "heroAccent"
  | "heroBody"
  | "heroAction"
  | "navigation"
  | "sectionHeading"
  | "sectionBody"
  | "cardTitle"
  | "cardMeta";

export type TypographyRegionSettings = {
  fontId: string;
  fontWeight: number;
  fontStyle: "normal" | "italic";
  fontSizePx: number;
  lineHeight: number;
  letterSpacingEm: number;
  textTransform: "none" | "uppercase" | "small-caps";
};

export type TypographyRegionDefinition = {
  id: TypographyRegionId;
  label: string;
};

export type FontCatalogEntry = {
  id: string;
  label: string;
  family: string;
  fallback: string;
  source: FontSource;
  weights: readonly number[];
  supportsItalic: boolean;
  googleFamily?: string;
  collection?: FontCollection;
  allowedRegions?: readonly TypographyRegionId[];
};

export const HANDWRITTEN_FONT_COLLECTIONS = [
  { id: "handwritten-signature", label: "Handwritten: Signature & calligraphy" },
  { id: "handwritten-casual", label: "Handwritten: Casual pen" },
  { id: "handwritten-marker", label: "Handwritten: Marker & brush" },
  { id: "handwritten-playful", label: "Handwritten: Playful display" },
] as const satisfies readonly { id: FontCollection; label: string }[];

type HandwrittenFontDefinition = readonly [
  id: string,
  family: string,
  weights: readonly number[],
  collection: FontCollection,
];

const HANDWRITTEN_FONT_DEFINITIONS: readonly HandwrittenFontDefinition[] = [
  // Signature and calligraphy
  ["aguafina-script", "Aguafina Script", [400], "handwritten-signature"],
  ["alex-brush", "Alex Brush", [400], "handwritten-signature"],
  ["allura", "Allura", [400], "handwritten-signature"],
  ["arizonia", "Arizonia", [400], "handwritten-signature"],
  ["babylonica", "Babylonica", [400], "handwritten-signature"],
  ["beau-rivage", "Beau Rivage", [400], "handwritten-signature"],
  ["bilbo", "Bilbo", [400], "handwritten-signature"],
  ["birthstone", "Birthstone", [400], "handwritten-signature"],
  ["bonheur-royale", "Bonheur Royale", [400], "handwritten-signature"],
  ["carattere", "Carattere", [400], "handwritten-signature"],
  ["clicker-script", "Clicker Script", [400], "handwritten-signature"],
  ["cookie", "Cookie", [400], "handwritten-signature"],
  ["corinthia", "Corinthia", [400, 700], "handwritten-signature"],
  ["dancing-script", "Dancing Script", [400, 500, 600, 700], "handwritten-signature"],
  ["ephesis", "Ephesis", [400], "handwritten-signature"],
  ["euphoria-script", "Euphoria Script", [400], "handwritten-signature"],
  ["fleur-de-leah", "Fleur De Leah", [400], "handwritten-signature"],
  ["great-vibes", "Great Vibes", [400], "handwritten-signature"],
  ["herr-von-muellerhoff", "Herr Von Muellerhoff", [400], "handwritten-signature"],
  ["imperial-script", "Imperial Script", [400], "handwritten-signature"],
  ["italianno", "Italianno", [400], "handwritten-signature"],
  ["kaushan-script", "Kaushan Script", [400], "handwritten-signature"],
  ["lavishly-yours", "Lavishly Yours", [400], "handwritten-signature"],
  ["luxurious-script", "Luxurious Script", [400], "handwritten-signature"],
  ["meow-script", "Meow Script", [400], "handwritten-signature"],
  ["monsieur-la-doulaise", "Monsieur La Doulaise", [400], "handwritten-signature"],
  ["montecarlo", "MonteCarlo", [400], "handwritten-signature"],
  ["ms-madi", "Ms Madi", [400], "handwritten-signature"],
  ["parisienne", "Parisienne", [400], "handwritten-signature"],
  ["petit-formal-script", "Petit Formal Script", [400], "handwritten-signature"],
  ["pinyon-script", "Pinyon Script", [400], "handwritten-signature"],
  ["qwigley", "Qwigley", [400], "handwritten-signature"],
  ["rochester", "Rochester", [400], "handwritten-signature"],
  ["rouge-script", "Rouge Script", [400], "handwritten-signature"],
  ["sacramento", "Sacramento", [400], "handwritten-signature"],
  ["satisfy", "Satisfy", [400], "handwritten-signature"],
  ["tangerine", "Tangerine", [400, 700], "handwritten-signature"],
  ["windsong", "WindSong", [400, 500], "handwritten-signature"],
  ["yellowtail", "Yellowtail", [400], "handwritten-signature"],

  // Natural handwriting and casual pen
  ["annie-use-your-telescope", "Annie Use Your Telescope", [400], "handwritten-casual"],
  ["architects-daughter", "Architects Daughter", [400], "handwritten-casual"],
  ["bad-script", "Bad Script", [400], "handwritten-casual"],
  ["caveat", "Caveat", [400, 500, 600, 700], "handwritten-casual"],
  ["cedarville-cursive", "Cedarville Cursive", [400], "handwritten-casual"],
  ["coming-soon", "Coming Soon", [400], "handwritten-casual"],
  ["covered-by-your-grace", "Covered By Your Grace", [400], "handwritten-casual"],
  ["dawning-of-a-new-day", "Dawning of a New Day", [400], "handwritten-casual"],
  ["delius", "Delius", [400], "handwritten-casual"],
  ["give-you-glory", "Give You Glory", [400], "handwritten-casual"],
  ["gloria-hallelujah", "Gloria Hallelujah", [400], "handwritten-casual"],
  ["handlee", "Handlee", [400], "handwritten-casual"],
  ["homemade-apple", "Homemade Apple", [400], "handwritten-casual"],
  ["indie-flower", "Indie Flower", [400], "handwritten-casual"],
  ["just-another-hand", "Just Another Hand", [400], "handwritten-casual"],
  ["kalam", "Kalam", [300, 400, 700], "handwritten-casual"],
  ["la-belle-aurore", "La Belle Aurore", [400], "handwritten-casual"],
  ["loved-by-the-king", "Loved by the King", [400], "handwritten-casual"],
  ["mansalva", "Mansalva", [400], "handwritten-casual"],
  ["nanum-pen-script", "Nanum Pen Script", [400], "handwritten-casual"],
  ["neucha", "Neucha", [400], "handwritten-casual"],
  ["nothing-you-could-do", "Nothing You Could Do", [400], "handwritten-casual"],
  ["oooh-baby", "Oooh Baby", [400], "handwritten-casual"],
  ["over-the-rainbow", "Over the Rainbow", [400], "handwritten-casual"],
  ["patrick-hand", "Patrick Hand", [400], "handwritten-casual"],
  ["patrick-hand-sc", "Patrick Hand SC", [400], "handwritten-casual"],
  ["reenie-beanie", "Reenie Beanie", [400], "handwritten-casual"],
  ["schoolbell", "Schoolbell", [400], "handwritten-casual"],
  ["shadows-into-light", "Shadows Into Light", [400], "handwritten-casual"],
  ["shadows-into-light-two", "Shadows Into Light Two", [400], "handwritten-casual"],
  ["sue-ellen-francisco", "Sue Ellen Francisco", [400], "handwritten-casual"],
  ["swanky-and-moo-moo", "Swanky and Moo Moo", [400], "handwritten-casual"],
  ["the-girl-next-door", "The Girl Next Door", [400], "handwritten-casual"],
  ["waiting-for-the-sunrise", "Waiting for the Sunrise", [400], "handwritten-casual"],
  ["walter-turncoat", "Walter Turncoat", [400], "handwritten-casual"],
  ["zeyada", "Zeyada", [400], "handwritten-casual"],

  // Marker and brush lettering
  ["amatic-sc", "Amatic SC", [400, 700], "handwritten-marker"],
  ["caveat-brush", "Caveat Brush", [400], "handwritten-marker"],
  ["chilanka", "Chilanka", [400], "handwritten-marker"],
  ["comforter-brush", "Comforter Brush", [400], "handwritten-marker"],
  ["delicious-handrawn", "Delicious Handrawn", [400], "handwritten-marker"],
  ["east-sea-dokdo", "East Sea Dokdo", [400], "handwritten-marker"],
  ["gaegu", "Gaegu", [300, 400, 700], "handwritten-marker"],
  ["gamja-flower", "Gamja Flower", [400], "handwritten-marker"],
  ["gochi-hand", "Gochi Hand", [400], "handwritten-marker"],
  ["grape-nuts", "Grape Nuts", [400], "handwritten-marker"],
  ["hachi-maru-pop", "Hachi Maru Pop", [400], "handwritten-marker"],
  ["hi-melody", "Hi Melody", [400], "handwritten-marker"],
  ["itim", "Itim", [400], "handwritten-marker"],
  ["kolker-brush", "Kolker Brush", [400], "handwritten-marker"],
  ["nanum-brush-script", "Nanum Brush Script", [400], "handwritten-marker"],
  ["permanent-marker", "Permanent Marker", [400], "handwritten-marker"],
  ["rock-salt", "Rock Salt", [400], "handwritten-marker"],
  ["sedgwick-ave", "Sedgwick Ave", [400], "handwritten-marker"],
  ["sedgwick-ave-display", "Sedgwick Ave Display", [400], "handwritten-marker"],
  ["short-stack", "Short Stack", [400], "handwritten-marker"],
  ["sriracha", "Sriracha", [400], "handwritten-marker"],
  ["water-brush", "Water Brush", [400], "handwritten-marker"],
  ["yomogi", "Yomogi", [400], "handwritten-marker"],

  // Playful and editorial handwriting
  ["amita", "Amita", [400, 700], "handwritten-playful"],
  ["are-you-serious", "Are You Serious", [400], "handwritten-playful"],
  ["berkshire-swash", "Berkshire Swash", [400], "handwritten-playful"],
  ["bonbon", "Bonbon", [400], "handwritten-playful"],
  ["borel", "Borel", [400], "handwritten-playful"],
  ["butterfly-kids", "Butterfly Kids", [400], "handwritten-playful"],
  ["calligraffitti", "Calligraffitti", [400], "handwritten-playful"],
  ["crafty-girls", "Crafty Girls", [400], "handwritten-playful"],
  ["delius-swash-caps", "Delius Swash Caps", [400], "handwritten-playful"],
  ["delius-unicase", "Delius Unicase", [400, 700], "handwritten-playful"],
  ["eagle-lake", "Eagle Lake", [400], "handwritten-playful"],
  ["fuggles", "Fuggles", [400], "handwritten-playful"],
  ["fuzzy-bubbles", "Fuzzy Bubbles", [400, 700], "handwritten-playful"],
  ["julee", "Julee", [400], "handwritten-playful"],
  ["just-me-again-down-here", "Just Me Again Down Here", [400], "handwritten-playful"],
  ["lakki-reddy", "Lakki Reddy", [400], "handwritten-playful"],
  ["leckerli-one", "Leckerli One", [400], "handwritten-playful"],
  ["merienda", "Merienda", [300, 400, 500, 600, 700, 800, 900], "handwritten-playful"],
  ["nerko-one", "Nerko One", [400], "handwritten-playful"],
  ["niconne", "Niconne", [400], "handwritten-playful"],
  ["pangolin", "Pangolin", [400], "handwritten-playful"],
  ["playpen-sans", "Playpen Sans", [100, 200, 300, 400, 500, 600, 700, 800], "handwritten-playful"],
  ["princess-sofia", "Princess Sofia", [400], "handwritten-playful"],
  ["rancho", "Rancho", [400], "handwritten-playful"],
  ["redressed", "Redressed", [400], "handwritten-playful"],
  ["romanesco", "Romanesco", [400], "handwritten-playful"],
  ["sofia", "Sofia", [400], "handwritten-playful"],
  ["sunshiney", "Sunshiney", [400], "handwritten-playful"],
  ["twinkle-star", "Twinkle Star", [400], "handwritten-playful"],
  ["vibur", "Vibur", [400], "handwritten-playful"],
  ["yesteryear", "Yesteryear", [400], "handwritten-playful"],
];

const HERO_ACCENT_HANDWRITTEN_FONTS: readonly FontCatalogEntry[] =
  HANDWRITTEN_FONT_DEFINITIONS.map(([id, family, weights, collection]) => ({
    id,
    label: family,
    family,
    fallback: "cursive",
    source: "web",
    weights,
    supportsItalic: false,
    googleFamily: family,
    collection,
    allowedRegions: ["heroAccent"],
  }));

export const FONT_CATALOG: readonly FontCatalogEntry[] = [
  { id: "manrope", label: "Manrope", family: "Manrope", fallback: "sans-serif", source: "local", weights: [400, 500, 600, 700, 800], supportsItalic: false },
  { id: "instrument-serif", label: "Instrument Serif", family: "Instrument Serif", fallback: "serif", source: "local", weights: [400], supportsItalic: true },
  { id: "jetbrains-mono", label: "JetBrains Mono", family: "JetBrains Mono", fallback: "monospace", source: "local", weights: [400, 500, 600, 700], supportsItalic: false },
  { id: "arial", label: "Arial", family: "Arial", fallback: "sans-serif", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "georgia", label: "Georgia", family: "Georgia", fallback: "serif", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "times-new-roman", label: "Times New Roman", family: "Times New Roman", fallback: "serif", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "trebuchet-ms", label: "Trebuchet MS", family: "Trebuchet MS", fallback: "sans-serif", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "verdana", label: "Verdana", family: "Verdana", fallback: "sans-serif", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "courier-new", label: "Courier New", family: "Courier New", fallback: "monospace", source: "system", weights: [400, 700], supportsItalic: true },
  { id: "dm-sans", label: "DM Sans", family: "DM Sans", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "DM Sans" },
  { id: "inter", label: "Inter", family: "Inter", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Inter" },
  { id: "space-grotesk", label: "Space Grotesk", family: "Space Grotesk", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: false, googleFamily: "Space Grotesk" },
  { id: "plus-jakarta-sans", label: "Plus Jakarta Sans", family: "Plus Jakarta Sans", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Plus Jakarta Sans" },
  { id: "work-sans", label: "Work Sans", family: "Work Sans", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Work Sans" },
  { id: "fraunces", label: "Fraunces", family: "Fraunces", fallback: "serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Fraunces" },
  { id: "dm-serif-display", label: "DM Serif Display", family: "DM Serif Display", fallback: "serif", source: "web", weights: [400], supportsItalic: true, googleFamily: "DM Serif Display" },
  { id: "libre-baskerville", label: "Libre Baskerville", family: "Libre Baskerville", fallback: "serif", source: "web", weights: [400, 700], supportsItalic: true, googleFamily: "Libre Baskerville" },
  { id: "playfair-display", label: "Playfair Display", family: "Playfair Display", fallback: "serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Playfair Display" },
  { id: "cormorant-garamond", label: "Cormorant Garamond", family: "Cormorant Garamond", fallback: "serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Cormorant Garamond" },
  { id: "ibm-plex-mono", label: "IBM Plex Mono", family: "IBM Plex Mono", fallback: "monospace", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "IBM Plex Mono" },
  { id: "geist", label: "Geist", family: "Geist", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Geist" },
  { id: "sora", label: "Sora", family: "Sora", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: false, googleFamily: "Sora" },
  { id: "outfit", label: "Outfit", family: "Outfit", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: false, googleFamily: "Outfit" },
  { id: "urbanist", label: "Urbanist", family: "Urbanist", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Urbanist" },
  { id: "instrument-sans", label: "Instrument Sans", family: "Instrument Sans", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Instrument Sans" },
  { id: "ibm-plex-sans", label: "IBM Plex Sans", family: "IBM Plex Sans", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "IBM Plex Sans" },
  { id: "bodoni-moda", label: "Bodoni Moda", family: "Bodoni Moda", fallback: "serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Bodoni Moda" },
  { id: "lora", label: "Lora", family: "Lora", fallback: "serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Lora" },
  { id: "newsreader", label: "Newsreader", family: "Newsreader", fallback: "serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Newsreader" },
  { id: "source-serif-4", label: "Source Serif 4", family: "Source Serif 4", fallback: "serif", source: "web", weights: [400, 600, 700], supportsItalic: true, googleFamily: "Source Serif 4" },
  { id: "spectral", label: "Spectral", family: "Spectral", fallback: "serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Spectral" },
  { id: "crimson-pro", label: "Crimson Pro", family: "Crimson Pro", fallback: "serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Crimson Pro" },
  { id: "syne", label: "Syne", family: "Syne", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: false, googleFamily: "Syne" },
  { id: "bricolage-grotesque", label: "Bricolage Grotesque", family: "Bricolage Grotesque", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: false, googleFamily: "Bricolage Grotesque" },
  { id: "abril-fatface", label: "Abril Fatface", family: "Abril Fatface", fallback: "serif", source: "web", weights: [400], supportsItalic: false, googleFamily: "Abril Fatface" },
  { id: "unbounded", label: "Unbounded", family: "Unbounded", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: false, googleFamily: "Unbounded" },
  { id: "space-mono", label: "Space Mono", family: "Space Mono", fallback: "monospace", source: "web", weights: [400, 700], supportsItalic: true, googleFamily: "Space Mono" },
  { id: "fira-code", label: "Fira Code", family: "Fira Code", fallback: "monospace", source: "web", weights: [400, 500, 600, 700], supportsItalic: false, googleFamily: "Fira Code" },
  { id: "dm-mono", label: "DM Mono", family: "DM Mono", fallback: "monospace", source: "web", weights: [400, 500], supportsItalic: true, googleFamily: "DM Mono" },
  { id: "archivo", label: "Archivo", family: "Archivo", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Archivo" },
  { id: "cabin", label: "Cabin", family: "Cabin", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Cabin" },
  { id: "noto-sans", label: "Noto Sans", family: "Noto Sans", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Noto Sans" },
  { id: "red-hat-display", label: "Red Hat Display", family: "Red Hat Display", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Red Hat Display" },
  { id: "rubik", label: "Rubik", family: "Rubik", fallback: "sans-serif", source: "web", weights: [400, 500, 600, 700, 800], supportsItalic: true, googleFamily: "Rubik" },
  { id: "merriweather", label: "Merriweather", family: "Merriweather", fallback: "serif", source: "web", weights: [400, 700], supportsItalic: true, googleFamily: "Merriweather" },
  { id: "eb-garamond", label: "EB Garamond", family: "EB Garamond", fallback: "serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "EB Garamond" },
  { id: "literata", label: "Literata", family: "Literata", fallback: "serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Literata" },
  { id: "alegreya", label: "Alegreya", family: "Alegreya", fallback: "serif", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Alegreya" },
  { id: "archivo-black", label: "Archivo Black", family: "Archivo Black", fallback: "sans-serif", source: "web", weights: [400], supportsItalic: false, googleFamily: "Archivo Black" },
  { id: "anton", label: "Anton", family: "Anton", fallback: "sans-serif", source: "web", weights: [400], supportsItalic: false, googleFamily: "Anton" },
  { id: "bebas-neue", label: "Bebas Neue", family: "Bebas Neue", fallback: "sans-serif", source: "web", weights: [400], supportsItalic: false, googleFamily: "Bebas Neue" },
  { id: "righteous", label: "Righteous", family: "Righteous", fallback: "sans-serif", source: "web", weights: [400], supportsItalic: false, googleFamily: "Righteous" },
  { id: "yeseva-one", label: "Yeseva One", family: "Yeseva One", fallback: "serif", source: "web", weights: [400], supportsItalic: false, googleFamily: "Yeseva One" },
  { id: "roboto-mono", label: "Roboto Mono", family: "Roboto Mono", fallback: "monospace", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Roboto Mono" },
  { id: "inconsolata", label: "Inconsolata", family: "Inconsolata", fallback: "monospace", source: "web", weights: [400, 500, 600, 700], supportsItalic: false, googleFamily: "Inconsolata" },
  { id: "source-code-pro", label: "Source Code Pro", family: "Source Code Pro", fallback: "monospace", source: "web", weights: [400, 500, 600, 700], supportsItalic: true, googleFamily: "Source Code Pro" },
  ...HERO_ACCENT_HANDWRITTEN_FONTS,
];

export function getFontsForRegion(regionId: TypographyRegionId): readonly FontCatalogEntry[] {
  return FONT_CATALOG.filter(
    (font) => !font.allowedRegions || font.allowedRegions.includes(regionId),
  );
}

export const TYPOGRAPHY_REGION_DEFINITIONS: readonly TypographyRegionDefinition[] = [
  { id: "heroMain", label: "Hero main" },
  { id: "heroAccent", label: "Hero accent" },
  { id: "heroBody", label: "Hero body" },
  { id: "heroAction", label: "Hero action" },
  { id: "navigation", label: "Navigation" },
  { id: "sectionHeading", label: "Section heading" },
  { id: "sectionBody", label: "Section body" },
  { id: "cardTitle", label: "Card title" },
  { id: "cardMeta", label: "Card meta" },
];

export const DEFAULT_REGION_SETTINGS: Record<TypographyRegionId, TypographyRegionSettings> = {
  heroMain: { fontId: "instrument-serif", fontWeight: 400, fontStyle: "normal", fontSizePx: 64, lineHeight: 1.15, letterSpacingEm: 0.012, textTransform: "none" },
  heroAccent: { fontId: "georgia", fontWeight: 400, fontStyle: "italic", fontSizePx: 70, lineHeight: 1.2, letterSpacingEm: 0.046, textTransform: "none" },
  heroBody: { fontId: "manrope", fontWeight: 400, fontStyle: "normal", fontSizePx: 18, lineHeight: 1.6, letterSpacingEm: 0, textTransform: "none" },
  heroAction: { fontId: "manrope", fontWeight: 700, fontStyle: "normal", fontSizePx: 14, lineHeight: 1.2, letterSpacingEm: 0, textTransform: "none" },
  navigation: { fontId: "manrope", fontWeight: 600, fontStyle: "normal", fontSizePx: 14, lineHeight: 1.2, letterSpacingEm: 0, textTransform: "none" },
  sectionHeading: { fontId: "manrope", fontWeight: 700, fontStyle: "normal", fontSizePx: 40, lineHeight: 1.05, letterSpacingEm: 0, textTransform: "none" },
  sectionBody: { fontId: "manrope", fontWeight: 400, fontStyle: "normal", fontSizePx: 18, lineHeight: 1.6, letterSpacingEm: 0, textTransform: "none" },
  cardTitle: { fontId: "manrope", fontWeight: 700, fontStyle: "normal", fontSizePx: 18, lineHeight: 1.3, letterSpacingEm: 0, textTransform: "none" },
  cardMeta: { fontId: "manrope", fontWeight: 500, fontStyle: "normal", fontSizePx: 13, lineHeight: 1.4, letterSpacingEm: 0, textTransform: "uppercase" },
};

function copySettings(settings: TypographyRegionSettings): TypographyRegionSettings {
  return { ...settings };
}

export function resetRegionSettings(regionId: TypographyRegionId): TypographyRegionSettings {
  return copySettings(DEFAULT_REGION_SETTINGS[regionId]);
}

export function resetAllRegionSettings(
  _settings: Record<TypographyRegionId, TypographyRegionSettings>,
): Record<TypographyRegionId, TypographyRegionSettings> {
  return Object.fromEntries(
    TYPOGRAPHY_REGION_DEFINITIONS.map(({ id }) => [id, resetRegionSettings(id)]),
  ) as Record<TypographyRegionId, TypographyRegionSettings>;
}
