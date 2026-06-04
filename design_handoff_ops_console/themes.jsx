// themes.jsx — token sets for Direction A (Atlas) and Direction B (Heritage).
// Each theme is a self-contained object passed to surface components as a prop.

const themeAtlas = {
  key: 'atlas',
  name: 'Atlas',
  tagline: 'Infrastructure-trust, Stripe-lean.',
  description: 'Off-white base, deep tea-leaf green as a single confident accent. Geist throughout; serif used only for editorial moments. Built to make a Bridge feel her business is on serious financial rails.',

  bg: '#F6F4EE',
  surface: '#FFFFFF',
  surfaceMuted: '#EFECE4',
  ink: '#0F1311',
  inkMuted: '#5A5D55',
  inkSubtle: '#9A9B92',
  border: '#E2DED1',
  borderStrong: '#CFC9B7',

  accent: '#1E5A3F',       // deep Kericho-tea green
  accentInk: '#FFFFFF',
  accentSoft: '#E4EBE2',
  accentSoftInk: '#1E5A3F',

  signal: '#B85C38',        // clay — used very sparingly for "live" pulses
  signalSoft: '#F4E6DD',

  ok: '#1E5A3F',
  warn: '#B07A18',

  sans: '"Geist", "Inter", system-ui, sans-serif',
  serif: '"Source Serif 4", Georgia, serif',
  mono: '"Geist Mono", ui-monospace, monospace',

  radius: 10,
  radiusSm: 6,
  radiusLg: 16,
};

const themeHeritage = {
  key: 'heritage',
  name: 'Heritage',
  tagline: 'Editorial warmth, Studio 189-lean.',
  description: 'Warm cream base, deep clay-cocoa accent, Instrument Serif for storytelling, Space Grotesk for product. Cultural register lives in copy voice, serif headlines, and producer-story treatment — never in pattern or ornament.',

  bg: '#EFE7D5',
  surface: '#F7F1E0',
  surfaceMuted: '#E6DEC9',
  ink: '#1A140C',
  inkMuted: '#5E5240',
  inkSubtle: '#9B8F73',
  border: '#D9CFB4',
  borderStrong: '#BFB291',

  accent: '#7A3E1F',        // deep clay / cocoa, NOT orange
  accentInk: '#F7F1E0',
  accentSoft: '#E2D5BA',
  accentSoftInk: '#7A3E1F',

  signal: '#3F5A3F',        // forest, used sparingly
  signalSoft: '#DCE2D3',

  ok: '#3F5A3F',
  warn: '#8A6A1E',

  sans: '"Space Grotesk", system-ui, sans-serif',
  serif: '"Instrument Serif", Georgia, serif',
  mono: '"JetBrains Mono", ui-monospace, monospace',

  radius: 4,
  radiusSm: 2,
  radiusLg: 8,
};

const allThemes = { atlas: themeAtlas, heritage: themeHeritage };

window.themeAtlas = themeAtlas;
window.themeHeritage = themeHeritage;
window.allThemes = allThemes;
