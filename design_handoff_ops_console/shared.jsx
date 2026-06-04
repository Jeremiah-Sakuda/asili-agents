// shared.jsx — primitives used across surfaces: placeholder image blocks,
// the Asili wordmark, agent dots, micro-icons. No theme-specific colors here;
// everything pulls from a `t` (theme) prop or CSS vars.

// Inline-SVG primitives. Pure stroke marks — no faces, no scenes.
const Mark = ({ t, size = 24, stroke = 1.5 }) => {
  // Asili "origin" mark — a centered circle nested in a square, suggesting
  // root + frame, not a logo of a specific thing. Same mark across themes,
  // colored by accent.
  const s = size;
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <rect x="2.5" y="2.5" width="19" height="19" rx="1" stroke={t.ink} strokeWidth={stroke}/>
      <circle cx="12" cy="12" r="5.5" stroke={t.accent} strokeWidth={stroke}/>
      <circle cx="12" cy="12" r="1.4" fill={t.accent}/>
    </svg>
  );
};

const Wordmark = ({ t, size = 18 }) => (
  <div style={{display:'flex',alignItems:'center',gap:8, color:t.ink}}>
    <Mark t={t} size={Math.round(size * 1.05)} />
    <span style={{
      fontFamily: t.sans,
      fontWeight: 600,
      fontSize: size,
      letterSpacing: t.key === 'heritage' ? '-0.01em' : '-0.02em',
    }}>Asili</span>
  </div>
);

// Labeled placeholder block. Mono caption. Used in every surface where a real
// photograph would go. Never draw faces.
const Placeholder = ({ t, label, w, h, tone = 'default', children, style = {} }) => {
  const palette = {
    default: { a: 'rgba(0,0,0,.06)', b: 'rgba(0,0,0,.025)', text: t.inkSubtle, bg: t.surfaceMuted },
    dark:    { a: 'rgba(255,255,255,.10)', b: 'rgba(255,255,255,.04)', text: 'rgba(255,255,255,.75)', bg: t.ink },
    accent:  { a: 'rgba(0,0,0,.07)', b: 'rgba(0,0,0,.02)', text: t.accentSoftInk, bg: t.accentSoft },
  }[tone];
  return (
    <div className="ph-stripe" style={{
      width: w, height: h,
      background: palette.bg,
      '--ph-a': palette.a, '--ph-b': palette.b,
      borderRadius: t.radius,
      display:'flex', alignItems:'flex-end', padding: 14,
      position:'relative', overflow:'hidden',
      ...style,
    }}>
      <div style={{
        fontFamily: t.mono, fontSize: 11, color: palette.text,
        textTransform:'uppercase', letterSpacing:'.06em',
      }}>{label}</div>
      {children}
    </div>
  );
};

// Tiny chip — used for tags, status pills, "AI" labels
const Chip = ({ t, children, tone = 'default', style = {} }) => {
  const palette = {
    default:{ bg: t.surfaceMuted, ink: t.inkMuted },
    accent: { bg: t.accentSoft, ink: t.accentSoftInk },
    ink:    { bg: t.ink,         ink: t.bg },
    signal: { bg: t.signalSoft,  ink: t.signal },
    ghost:  { bg: 'transparent', ink: t.inkMuted, border: '1px solid ' + t.border },
  }[tone];
  return (
    <span style={{
      display:'inline-flex', alignItems:'center', gap: 6,
      fontFamily: t.mono, fontSize: 10.5, letterSpacing:'.04em',
      textTransform: 'uppercase',
      padding: '4px 8px',
      borderRadius: t.radiusSm,
      background: palette.bg, color: palette.ink,
      border: palette.border || 'none',
      ...style,
    }}>{children}</span>
  );
};

const Button = ({ t, children, kind = 'primary', size = 'md', style = {} }) => {
  const sz = size === 'sm'
    ? { padY: 8,  padX: 14, font: 13 }
    : size === 'lg'
      ? { padY: 14, padX: 22, font: 15 }
      : { padY: 11, padX: 18, font: 14 };
  const palette = {
    primary: { bg: t.ink, ink: t.bg, border: t.ink },
    accent:  { bg: t.accent, ink: t.accentInk, border: t.accent },
    ghost:   { bg: 'transparent', ink: t.ink, border: t.borderStrong },
    quiet:   { bg: t.surface, ink: t.ink, border: t.border },
  }[kind];
  return (
    <button style={{
      display:'inline-flex', alignItems:'center', gap: 8,
      padding: `${sz.padY}px ${sz.padX}px`,
      fontFamily: t.sans, fontSize: sz.font, fontWeight: 500,
      background: palette.bg, color: palette.ink,
      border: `1px solid ${palette.border}`,
      borderRadius: t.radius,
      cursor: 'pointer',
      letterSpacing: '-0.005em',
      ...style,
    }}>{children}</button>
  );
};

// A pulse dot used to indicate "live"
const PulseDot = ({ t, color }) => {
  const c = color || t.signal;
  return (
    <span style={{position:'relative', width:8, height:8, display:'inline-block'}}>
      <span style={{
        position:'absolute', inset:0, borderRadius:'50%', background: c,
        animation: 'asili-pulse 1.6s ease-out infinite', opacity:.4,
      }}/>
      <span style={{
        position:'absolute', inset:1, borderRadius:'50%', background: c,
      }}/>
      <style>{`@keyframes asili-pulse { 0%{transform:scale(1);opacity:.5} 100%{transform:scale(2.4);opacity:0} }`}</style>
    </span>
  );
};

// Minor display helper — a thin top/bottom rule line
const Rule = ({ t, style = {} }) => (
  <div style={{ height: 1, background: t.border, ...style }} />
);

// Helper: format big number with thin separator
const fmt = (n) => n.toLocaleString('en-US');

Object.assign(window, { Mark, Wordmark, Placeholder, Chip, Button, PulseDot, Rule, fmt });
