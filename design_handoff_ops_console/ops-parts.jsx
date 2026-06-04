// ops-parts.jsx — presentational primitives for the Operations Console.
// Pure Atlas token usage (window.themeAtlas) + shared.jsx primitives (Chip,
// Button, PulseDot, Rule, Mark). No new colors, fonts, or radii are introduced;
// the trace/feed/card vocabulary is lifted from admin.jsx + behindops.jsx.

const tO = window.themeAtlas;

// ── Asili mark (updated logo) ────────────────────────────────────────
// The "A" peak — two strokes meeting at the apex with the accent dot near the
// crossbar. Matches the lockup in the brand guide / company overview.
const AsiliMark = ({ size = 18, ink = tO.ink, accent = tO.accent }) => (
  <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-hidden="true" style={{ display: 'block' }}>
    <path d="M32 7 L58 57 M32 7 L6 57" stroke={ink} strokeWidth={5} strokeLinecap="round" />
    <circle cx="32" cy="41" r="4.5" fill={accent} />
  </svg>
);

// ── Asili lockup (console-scale) ───────────────────────────────────────
const OpsLockup = ({ size = 15 }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: tO.ink }}>
    <AsiliMark size={Math.round(size * 1.2)} />
    <span style={{ fontFamily: tO.sans, fontWeight: 600, fontSize: size, letterSpacing: '-0.02em' }}>Asili</span>
  </div>
);

// ── Panel chrome (mirrors admin.jsx Panel) ─────────────────────────────
const OpsPanel = ({ eyebrow, title, right, children, style = {}, bodyStyle = {} }) => (
  <div style={{
    background: tO.surface, border: `1px solid ${tO.border}`,
    borderRadius: tO.radiusLg, display: 'flex', flexDirection: 'column',
    minHeight: 0, ...style,
  }}>
    {(eyebrow || title || right) && (
      <div style={{
        display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
        gap: 14, padding: '16px 18px 14px', borderBottom: `1px solid ${tO.border}`,
      }}>
        <div>
          {eyebrow && (
            <div style={{
              fontFamily: tO.mono, fontSize: 9.5, color: tO.inkSubtle,
              textTransform: 'uppercase', letterSpacing: '.1em', marginBottom: 5,
            }}>{eyebrow}</div>
          )}
          {title && (
            <h3 style={{
              margin: 0, fontFamily: tO.sans, fontSize: 15, fontWeight: 600,
              color: tO.ink, letterSpacing: '-0.01em',
            }}>{title}</h3>
          )}
        </div>
        {right}
      </div>
    )}
    <div style={{ padding: '16px 18px', flex: 1, minHeight: 0, ...bodyStyle }}>{children}</div>
  </div>
);

// ── Agent avatar — rounded initials badge (admin AgentBadgeMini family) ─
const AGENT_VISUAL = {
  'Operations Manager': { initials: 'OM', tone: 'ink' },
  'Messaging':          { initials: 'M',  tone: 'accent' },
  'Pricing':            { initials: 'P',  tone: 'default' },
};
const AgentAvatar = ({ agent, tone, size = 28, initials }) => {
  const v = AGENT_VISUAL[agent] || { initials: initials || (agent || '?').slice(0, 1), tone: tone || 'default' };
  const useTone = tone || v.tone;
  const text = initials || v.initials;
  const palette = {
    ink:     { bg: tO.ink, ink: tO.bg },
    accent:  { bg: tO.accentSoft, ink: tO.accent },
    default: { bg: tO.surfaceMuted, ink: tO.ink },
    signal:  { bg: tO.signalSoft, ink: tO.signal },
  }[useTone];
  return (
    <div style={{
      width: size, height: size, borderRadius: 6, flexShrink: 0,
      background: palette.bg, color: palette.ink,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: tO.mono, fontSize: size * 0.4, fontWeight: 500, letterSpacing: '.02em',
    }}>{text}</div>
  );
};

// ── Agent step — decision-trace styled feed item, with hand-off rail ────
// Renders one streamed step: numbered position on a connector rail, agent
// name + role + time, then the one-line reasoning trace in a bordered box.
const AgentStep = ({ step, index, total, isHandoff, justLanded }) => {
  const isOrchestrator = step.agent === 'Operations Manager';
  return (
    <div
      className={justLanded ? 'ops-step-in' : undefined}
      style={{ display: 'grid', gridTemplateColumns: '36px 1fr', gap: 12, position: 'relative' }}
    >
      {/* Rail */}
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <AgentAvatar agent={step.agent} size={32} />
        {index < total - 1 && (
          <div style={{ width: 2, flex: 1, minHeight: 18, background: tO.border, marginTop: 4 }} />
        )}
      </div>

      {/* Body */}
      <div style={{ paddingBottom: index < total - 1 ? 16 : 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
          <span style={{ fontFamily: tO.sans, fontSize: 13.5, fontWeight: 600, color: tO.ink, letterSpacing: '-0.005em' }}>
            {step.agent}
          </span>
          <span style={{ fontFamily: tO.mono, fontSize: 9.5, color: tO.inkSubtle, textTransform: 'uppercase', letterSpacing: '.07em' }}>
            {step.role}
          </span>
          <span style={{ flex: 1 }} />
          <span style={{ fontFamily: tO.mono, fontSize: 10, color: tO.inkSubtle }}>{step.t}</span>
        </div>

        {isHandoff && (
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 5, margin: '7px 0 0',
            fontFamily: tO.mono, fontSize: 9, color: tO.accent,
            textTransform: 'uppercase', letterSpacing: '.08em',
          }}>
            <span style={{ fontSize: 11, lineHeight: 1 }}>↳</span> hand-off
          </div>
        )}

        {/* Reasoning trace box (admin TraceBox / ReasoningLine styling) */}
        <div style={{
          marginTop: 8, padding: '9px 12px',
          background: isOrchestrator ? tO.bg : tO.accentSoft,
          border: `1px solid ${isOrchestrator ? tO.border : 'rgba(30,90,63,.22)'}`,
          borderRadius: tO.radius,
          fontFamily: tO.sans, fontSize: 12.5, lineHeight: 1.45,
          color: isOrchestrator ? tO.ink : tO.accent,
        }}>{step.trace}</div>

        {step.grounds && step.grounds.length > 0 && (
          <div style={{
            marginTop: 7, display: 'flex', alignItems: 'center', gap: 6,
            fontFamily: tO.mono, fontSize: 9.5, color: tO.inkSubtle,
            textTransform: 'uppercase', letterSpacing: '.06em',
          }}>
            <span style={{ color: tO.accent }}>✓</span> grounded · {step.grounds.join(' · ')}
          </div>
        )}
      </div>
    </div>
  );
};

// ── Business-state fact row ────────────────────────────────────────────
const FactRow = ({ fact, lit }) => {
  const toneInk = fact.tone === 'signal' ? tO.signal : fact.tone === 'accent' ? tO.accent : tO.ink;
  return (
    <div
      className={lit ? 'ops-fact-lit' : undefined}
      style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 14,
        padding: '11px 12px', borderRadius: tO.radius,
        border: `1px solid ${lit ? 'rgba(30,90,63,.30)' : 'transparent'}`,
        background: lit ? tO.accentSoft : 'transparent',
        transition: 'background .35s ease, border-color .35s ease',
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ fontFamily: tO.mono, fontSize: 9.5, color: tO.inkSubtle, textTransform: 'uppercase', letterSpacing: '.07em' }}>{fact.k}</div>
        <div style={{ fontFamily: tO.sans, fontSize: 14, fontWeight: 600, color: toneInk, letterSpacing: '-0.01em', marginTop: 3 }}>{fact.v}</div>
      </div>
      {fact.sub && (
        <div style={{ fontFamily: tO.sans, fontSize: 11, color: tO.inkMuted, textAlign: 'right', whiteSpace: 'nowrap' }}>{fact.sub}</div>
      )}
    </div>
  );
};

// ── Chat bubbles ───────────────────────────────────────────────────────
const ChatRow = ({ side, avatar, children, caption }) => {
  const isOut = side === 'out';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: isOut ? 'flex-end' : 'flex-start', gap: 5 }}>
      <div style={{ display: 'flex', flexDirection: isOut ? 'row-reverse' : 'row', alignItems: 'flex-end', gap: 9, maxWidth: '82%' }}>
        {avatar}
        <div>{children}</div>
      </div>
      {caption && (
        <div style={{ fontFamily: tO.mono, fontSize: 9.5, color: tO.inkSubtle, textTransform: 'uppercase', letterSpacing: '.06em', padding: isOut ? '0 38px 0 0' : '0 0 0 38px' }}>{caption}</div>
      )}
    </div>
  );
};

const Bubble = ({ side, children, muted }) => {
  const isOut = side === 'out';
  return (
    <div style={{
      padding: '11px 14px', borderRadius: 14,
      borderBottomRightRadius: isOut ? 4 : 14, borderBottomLeftRadius: isOut ? 14 : 4,
      background: isOut ? tO.ink : tO.surfaceMuted,
      color: isOut ? tO.bg : tO.ink,
      border: isOut ? 'none' : `1px solid ${tO.border}`,
      opacity: muted ? 0.55 : 1,
      fontFamily: tO.sans, fontSize: 14, lineHeight: 1.5, letterSpacing: '-0.005em',
    }}>{children}</div>
  );
};

const CustomerAvatar = ({ initials }) => (
  <div style={{
    width: 28, height: 28, borderRadius: '50%', flexShrink: 0,
    background: tO.surfaceMuted, border: `1px solid ${tO.border}`, color: tO.inkMuted,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    fontFamily: tO.mono, fontSize: 10.5, fontWeight: 500,
  }}>{initials}</div>
);

// ── Sources line (under a drafted reply) ───────────────────────────────
const SourcesLine = ({ sources }) => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
    <span style={{ fontFamily: tO.mono, fontSize: 9.5, color: tO.inkSubtle, textTransform: 'uppercase', letterSpacing: '.07em' }}>Sources</span>
    {sources.map((s, i) => (
      <Chip key={i} t={tO} tone="ghost" style={{ fontSize: 9.5 }}>{s}</Chip>
    ))}
  </div>
);

// ── Inline flag marker (proof screen) ──────────────────────────────────
// Wraps a token (stock number / price) and pins an error/success note to it.
const FlaggedToken = ({ text, marker, note }) => {
  const isErr = marker === 'error';
  const color = isErr ? tO.signal : tO.accent;
  const soft = isErr ? tO.signalSoft : tO.accentSoft;
  return (
    <span style={{ whiteSpace: 'nowrap' }}>
      <strong style={{ fontWeight: 600, color, borderBottom: `2px solid ${color}`, paddingBottom: 1 }}>{text}</strong>
      <span style={{
        marginLeft: 6, display: 'inline-flex', alignItems: 'center', gap: 4, verticalAlign: 'baseline',
        padding: '2px 7px', borderRadius: tO.radiusSm, background: soft, color,
        fontFamily: tO.mono, fontSize: 9, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '.05em',
      }}>
        <span style={{ fontSize: 10, lineHeight: 1 }}>{isErr ? '✕' : '✓'}</span>{note}
      </span>
    </span>
  );
};

// Status pill summarizing a panel verdict (error vs success)
const VerdictPill = ({ marker, children }) => {
  const isErr = marker === 'error';
  const color = isErr ? tO.signal : tO.accent;
  const soft = isErr ? tO.signalSoft : tO.accentSoft;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 7,
      padding: '6px 11px', borderRadius: 99, background: soft, color,
      fontFamily: tO.mono, fontSize: 10, fontWeight: 500, textTransform: 'uppercase', letterSpacing: '.07em',
    }}>
      <span style={{ fontSize: 12, lineHeight: 1 }}>{isErr ? '✕' : '✓'}</span>{children}
    </span>
  );
};

Object.assign(window, {
  tO, AsiliMark, OpsLockup, OpsPanel, AgentAvatar, AgentStep, FactRow,
  ChatRow, Bubble, CustomerAvatar, SourcesLine, FlaggedToken, VerdictPill, AGENT_VISUAL,
});
