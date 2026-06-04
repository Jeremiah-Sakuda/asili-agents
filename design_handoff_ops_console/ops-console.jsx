// ops-console.jsx — the two demo screens:
//   1. OperationsConsole — one screen, three regions (business state ·
//      conversation · agent activity), a Run trigger, and an approval gate.
//   2. ProofScreen — "One model alone" vs "Asili operations team" split.
// Both read entirely from window.mockAgentService / scenario data so the demo
// is driven by React state only (no localStorage), ready to swap for ADK.

const tC = window.themeAtlas;

// Small helper: reuse the shared Button but make it clickable.
const ClickBtn = ({ onClick, disabled, children, ...p }) => (
  <span
    onClick={disabled ? undefined : onClick}
    style={{ display: 'inline-flex', cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.5 : 1 }}
  >
    <Button t={tC} {...p}>{children}</Button>
  </span>
);

// ── Segmented screen toggle ────────────────────────────────────────────
const SegToggle = ({ value, onChange, options }) => (
  <div style={{ display: 'inline-flex', background: tC.surface, border: `1px solid ${tC.border}`, borderRadius: tC.radius, padding: 2 }}>
    {options.map((o) => {
      const active = o.value === value;
      return (
        <span key={o.value} onClick={() => onChange(o.value)} style={{
          padding: '6px 14px', borderRadius: tC.radiusSm, cursor: 'pointer',
          fontFamily: tC.sans, fontSize: 12.5, fontWeight: active ? 500 : 400,
          color: active ? tC.bg : tC.inkMuted, background: active ? tC.ink : 'transparent',
          letterSpacing: '-0.005em', whiteSpace: 'nowrap',
        }}>{o.label}</span>
      );
    })}
  </div>
);

// ── Top bar (shared) ───────────────────────────────────────────────────
const TopBar = ({ screen, setScreen, children }) => (
  <div style={{
    display: 'flex', alignItems: 'center', gap: 18, flexShrink: 0,
    padding: '12px 22px', borderBottom: `1px solid ${tC.border}`, background: tC.bg,
  }}>
    <OpsLockup size={15} />
    <span style={{ width: 1, height: 22, background: tC.border }} />
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{ fontFamily: tC.sans, fontSize: 14, fontWeight: 600, color: tC.ink, letterSpacing: '-0.01em' }}>Operations Console</span>
      <Chip t={tC} tone="ghost">{SCENARIO.bridge.name} · {SCENARIO.bridge.lane}</Chip>
    </div>
    <span style={{ flex: 1 }} />
    <SegToggle value={screen} onChange={setScreen} options={[
      { value: 'console', label: 'Console' },
      { value: 'proof', label: 'Proof' },
    ]} />
    {children}
  </div>
);

// ════════════════════════════════════════════════════════════════════════
// 1 · OPERATIONS CONSOLE
// ════════════════════════════════════════════════════════════════════════
const OperationsConsole = ({ phase, steps, facts, litFacts, draft, messages, sent, onApprove, onReject, draftBody, setDraftBody, editing, setEditing }) => {
  const convoRef = React.useRef(null);
  React.useEffect(() => {
    if (convoRef.current) convoRef.current.scrollTop = convoRef.current.scrollHeight;
  }, [messages.length, draft, sent, editing]);

  return (
    <div style={{
      flex: 1, minHeight: 0, display: 'grid',
      gridTemplateColumns: '300px minmax(0,1fr) 432px', gap: 16, padding: 16,
      background: tC.bg,
    }}>
      {/* ── LEFT · Business state ─────────────────────────────── */}
      <OpsPanel eyebrow="Grounded data" title="Business state"
        right={<Chip t={tC} tone="ghost">live</Chip>}
        bodyStyle={{ padding: '10px 12px', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {facts.map((f) => <FactRow key={f.id} fact={f} lit={litFacts.has(f.id)} />)}
        <div style={{ marginTop: 'auto', paddingTop: 12 }}>
          <div style={{ fontFamily: tC.mono, fontSize: 9.5, color: tC.inkSubtle, textTransform: 'uppercase', letterSpacing: '.06em', lineHeight: 1.5, padding: '0 12px' }}>
            What the agents used to decide. Highlighted rows were verified against live data this run.
          </div>
        </div>
      </OpsPanel>

      {/* ── CENTER · Conversation ─────────────────────────────── */}
      <OpsPanel eyebrow={SCENARIO.customer.channel} title={SCENARIO.customer.name}
        right={<Chip t={tC} tone={sent ? 'accent' : 'default'}>{sent ? 'replied' : 'awaiting reply'}</Chip>}
        bodyStyle={{ padding: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div ref={convoRef} style={{ flex: 1, overflow: 'auto', padding: '18px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
          {messages.map((m) => (
            <ChatRow key={m.id} side={m.dir === 'in' ? 'in' : 'out'}
              avatar={m.dir === 'in' ? <CustomerAvatar initials={SCENARIO.customer.initials} /> : <AgentAvatar agent="Messaging" size={28} />}
              caption={m.dir === 'out' ? `Sent · ${m.at} · via ${m.from} agent` : `${m.from} · ${m.at}`}>
              <Bubble side={m.dir === 'in' ? 'in' : 'out'}>{m.body}</Bubble>
            </ChatRow>
          ))}

          {/* Working indicator */}
          {phase === 'running' && (
            <ChatRow side="out" avatar={<AgentAvatar agent="Operations Manager" size={28} />}>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: 9, padding: '11px 14px', borderRadius: 14, borderBottomRightRadius: 4, background: tC.surfaceMuted, border: `1px solid ${tC.border}` }}>
                <PulseDot t={tC} color={tC.accent} />
                <span style={{ fontFamily: tC.mono, fontSize: 11, color: tC.inkMuted, textTransform: 'uppercase', letterSpacing: '.06em' }}>Agents composing reply…</span>
              </div>
            </ChatRow>
          )}

          {/* Approval gate */}
          {draft && (phase === 'review' || phase === 'rejected') && (
            <DraftCard
              draft={draft} body={draftBody} setBody={setDraftBody}
              editing={editing} setEditing={setEditing}
              rejected={phase === 'rejected'}
              onApprove={onApprove} onReject={onReject}
            />
          )}
        </div>
      </OpsPanel>

      {/* ── RIGHT · Agent activity (focal) ────────────────────── */}
      <OpsPanel eyebrow="Multi-agent collaboration" title="Agent activity"
        right={phase === 'running'
          ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontFamily: tC.mono, fontSize: 10, color: tC.accent, textTransform: 'uppercase', letterSpacing: '.07em' }}><PulseDot t={tC} color={tC.accent} /> streaming</span>
          : <Chip t={tC} tone="ghost">{steps.length}/{AGENT_STEPS.length} steps</Chip>}
        bodyStyle={{ overflow: 'auto', padding: '18px 18px' }}>
        {steps.length === 0 && phase === 'idle' && (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', gap: 10, color: tC.inkSubtle, padding: '40px 20px' }}>
            <AgentAvatar agent="Operations Manager" size={40} />
            <div style={{ fontFamily: tC.sans, fontSize: 13.5, color: tC.inkMuted, lineHeight: 1.5, maxWidth: 240 }}>
              Press <strong style={{ color: tC.ink }}>Run agents</strong> to watch the operations team handle this message — routing, grounding, pricing, and composing a reply.
            </div>
          </div>
        )}
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {steps.map((s, i) => (
            <AgentStep key={s.id} step={s} index={i} total={AGENT_STEPS.length}
              isHandoff={i > 0 && steps[i - 1].agent !== s.agent}
              justLanded={i === steps.length - 1 && phase === 'running'} />
          ))}
        </div>
        {phase !== 'idle' && steps.length === AGENT_STEPS.length && (
          <div style={{ marginTop: 16, paddingTop: 14, borderTop: `1px solid ${tC.border}`, display: 'flex', alignItems: 'center', gap: 8, fontFamily: tC.mono, fontSize: 10, color: tC.inkSubtle, textTransform: 'uppercase', letterSpacing: '.06em' }}>
            <span style={{ color: tC.accent }}>✓</span> 4 hand-offs · reply drafted for approval
          </div>
        )}
      </OpsPanel>
    </div>
  );
};

// ── Draft / approval-gate card ─────────────────────────────────────────
const DraftCard = ({ draft, body, setBody, editing, setEditing, rejected, onApprove, onReject }) => (
  <div style={{
    border: `1px solid ${rejected ? tC.border : 'rgba(30,90,63,.30)'}`, borderRadius: tC.radiusLg,
    background: tC.surface, overflow: 'hidden', opacity: rejected ? 0.6 : 1,
  }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 9, padding: '11px 14px', borderBottom: `1px solid ${tC.border}`, background: tC.bg }}>
      <AgentAvatar agent={draft.by} size={22} />
      <span style={{ fontFamily: tC.mono, fontSize: 10, color: tC.inkSubtle, textTransform: 'uppercase', letterSpacing: '.07em' }}>
        Draft reply · {draft.by} agent
      </span>
      <span style={{ flex: 1 }} />
      <span style={{ fontFamily: tC.mono, fontSize: 10, color: rejected ? tC.signal : tC.accent, textTransform: 'uppercase', letterSpacing: '.07em' }}>
        {rejected ? '✕ rejected' : '● awaiting approval'}
      </span>
    </div>

    <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {editing ? (
        <textarea value={body} onChange={(e) => setBody(e.target.value)} rows={4} style={{
          width: '100%', resize: 'vertical', boxSizing: 'border-box',
          fontFamily: tC.sans, fontSize: 14, lineHeight: 1.5, color: tC.ink,
          padding: '10px 12px', borderRadius: tC.radius, border: `1px solid ${tC.borderStrong}`, background: tC.bg, outline: 'none',
        }} />
      ) : (
        <div style={{ fontFamily: tC.sans, fontSize: 14, lineHeight: 1.55, color: tC.ink }}>{body}</div>
      )}

      <SourcesLine sources={draft.sources} />

      {!rejected && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, paddingTop: 2 }}>
          {editing ? (
            <React.Fragment>
              <ClickBtn kind="accent" size="sm" onClick={onApprove}>✓ Approve &amp; send edit</ClickBtn>
              <ClickBtn kind="quiet" size="sm" onClick={() => setEditing(false)}>Cancel</ClickBtn>
            </React.Fragment>
          ) : (
            <React.Fragment>
              <ClickBtn kind="accent" size="sm" onClick={onApprove}>✓ Approve</ClickBtn>
              <ClickBtn kind="quiet" size="sm" onClick={() => setEditing(true)}>Edit</ClickBtn>
              <ClickBtn kind="ghost" size="sm" onClick={onReject}>Reject</ClickBtn>
            </React.Fragment>
          )}
        </div>
      )}
      {rejected && (
        <div style={{ fontFamily: tC.mono, fontSize: 10, color: tC.inkSubtle, textTransform: 'uppercase', letterSpacing: '.06em' }}>
          Draft rejected — re-run when ready.
        </div>
      )}
    </div>
  </div>
);

// ════════════════════════════════════════════════════════════════════════
// 2 · PROOF SCREEN — single model vs operations team
// ════════════════════════════════════════════════════════════════════════
const ProofPanel = ({ side, marker }) => {
  const isErr = marker === 'error';
  return (
    <OpsPanel
      style={{ borderColor: isErr ? 'rgba(184,92,56,.30)' : 'rgba(30,90,63,.30)' }}
      eyebrow={side.sub}
      title={<span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>{isErr ? <AgentAvatar initials="AI" tone="default" size={26} /> : <AgentAvatar agent="Operations Manager" tone="ink" size={26} />}{side.label}</span>}
      right={<VerdictPill marker={marker}>{isErr ? '2 errors' : 'verified'}</VerdictPill>}
      bodyStyle={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* The answer */}
      <div style={{
        padding: '14px 16px', borderRadius: tC.radiusLg,
        background: tC.surfaceMuted, border: `1px solid ${tC.border}`,
        fontFamily: tC.sans, fontSize: 15, lineHeight: 1.85, color: tC.ink,
      }}>
        {side.reply.map((seg, i) => seg.flag
          ? <FlaggedToken key={i} text={seg.text} marker={seg.flag.marker} note={seg.flag.note} />
          : <span key={i}>{seg.text}</span>)}
      </div>

      {/* Verdict line */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <span style={{ color: isErr ? tC.signal : tC.accent, fontSize: 15, lineHeight: 1.4 }}>{isErr ? '✕' : '✓'}</span>
        <span style={{ fontFamily: tC.serif, fontSize: 16, lineHeight: 1.45, color: tC.ink, letterSpacing: '-0.005em' }}>{side.verdict}</span>
      </div>

      {/* Marker summary */}
      <div style={{ marginTop: 'auto', paddingTop: 14, borderTop: `1px solid ${tC.border}`, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {side.reply.filter((s) => s.flag).map((s, i) => (
          <VerdictPill key={i} marker={s.flag.marker}>{s.flag.note}</VerdictPill>
        ))}
      </div>
    </OpsPanel>
  );
};

const ProofScreen = () => (
  <div style={{ flex: 1, minHeight: 0, overflow: 'auto', background: tC.bg, display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '34px 28px 40px' }}>
    <div style={{ width: '100%', maxWidth: 1080, display: 'flex', flexDirection: 'column', gap: 22 }}>
      {/* Header + shared question */}
      <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 16 }}>
        <div style={{ fontFamily: tC.mono, fontSize: 11, color: tC.inkSubtle, textTransform: 'uppercase', letterSpacing: '.1em' }}>
          Same question · two ways to answer it
        </div>
        <h1 style={{ margin: 0, fontFamily: tC.sans, fontSize: 30, fontWeight: 600, letterSpacing: '-0.025em', color: tC.ink }}>
          One model alone vs. an operations team
        </h1>
        <div style={{ display: 'inline-flex', alignItems: 'flex-end', gap: 10, maxWidth: 620, padding: '14px 18px', borderRadius: 16, borderBottomLeftRadius: 4, background: tC.surfaceMuted, border: `1px solid ${tC.border}` }}>
          <CustomerAvatar initials={SCENARIO.customer.initials} />
          <span style={{ fontFamily: tC.sans, fontSize: 15.5, lineHeight: 1.5, color: tC.ink, textAlign: 'left' }}>{PROOF.question}</span>
        </div>
        <div style={{ fontFamily: tC.mono, fontSize: 10, color: tC.inkSubtle, textTransform: 'uppercase', letterSpacing: '.06em' }}>
          {SCENARIO.customer.name} · {SCENARIO.bridge.name}
        </div>
      </div>

      {/* Split */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 18, alignItems: 'stretch' }}>
        <ProofPanel side={PROOF.left} marker="error" />
        <ProofPanel side={PROOF.right} marker="success" />
      </div>

      <div style={{ textAlign: 'center', fontFamily: tC.serif, fontSize: 17, color: tC.inkMuted, fontStyle: 'italic', letterSpacing: '-0.005em' }}>
        Specialized agents check stock and price against real data — so the answer is one you can actually send.
      </div>
    </div>
  </div>
);

// ════════════════════════════════════════════════════════════════════════
// APP SHELL — drives both screens from React state via the mock service
// ════════════════════════════════════════════════════════════════════════
function OpsApp() {
  const [screen, setScreen] = React.useState('console');

  // Console run state
  const [phase, setPhase] = React.useState('idle'); // idle | running | review | rejected | sent
  const [steps, setSteps] = React.useState([]);
  const [facts, setFacts] = React.useState(() => mockAgentService.getBusinessFacts());
  const [litFacts, setLitFacts] = React.useState(() => new Set());
  const [draft, setDraft] = React.useState(null);
  const [draftBody, setDraftBody] = React.useState('');
  const [editing, setEditing] = React.useState(false);
  const [messages, setMessages] = React.useState(() => mockAgentService.getConversation().messages);
  const ctrlRef = React.useRef(null);

  const reset = React.useCallback(() => {
    if (ctrlRef.current) ctrlRef.current.abort();
    setPhase('idle'); setSteps([]); setEditing(false);
    setFacts(mockAgentService.getBusinessFacts());
    setLitFacts(new Set()); setDraft(null); setDraftBody('');
    setMessages(mockAgentService.getConversation().messages);
  }, []);

  const run = React.useCallback(async () => {
    if (ctrlRef.current) ctrlRef.current.abort();
    const ctrl = new AbortController(); ctrlRef.current = ctrl;
    // fresh start
    setSteps([]); setEditing(false); setDraft(null); setDraftBody('');
    setFacts(mockAgentService.getBusinessFacts()); setLitFacts(new Set());
    setMessages(mockAgentService.getConversation().messages);
    setPhase('running');
    try {
      await mockAgentService.run({
        signal: ctrl.signal,
        onStep: (step) => {
          setSteps((prev) => [...prev, step]);
          if (step.grounds && step.grounds.length) {
            setLitFacts((prev) => { const n = new Set(prev); step.grounds.forEach((g) => n.add(g)); return n; });
          }
        },
        onBundle: (bf) => setFacts((prev) => prev.some((f) => f.id === bf.id) ? prev : [...prev, bf]),
        onDraft: (d) => { setDraft(d); setDraftBody(d.body); setPhase('review'); },
      });
    } catch (e) { /* aborted — ignore */ }
  }, []);

  const approve = React.useCallback(async () => {
    const ctrl = ctrlRef.current || new AbortController();
    const res = await mockAgentService.approve(draft.id, draftBody, { signal: ctrl.signal });
    setMessages((prev) => [...prev, { id: 'm_out', dir: 'out', from: draft.by, body: res.body, at: res.at }]);
    setDraft(null); setEditing(false); setPhase('sent');
  }, [draft, draftBody]);

  const reject = React.useCallback(() => { setPhase('rejected'); setEditing(false); }, []);

  const running = phase === 'running';
  const runLabel = running ? 'Agents working…' : (phase === 'idle' ? 'Run agents' : 'Re-run');

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'flex', flexDirection: 'column', background: tC.bg, overflow: 'hidden' }}>
      <TopBar screen={screen} setScreen={setScreen}>
        {screen === 'console' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <ClickBtn kind="accent" size="sm" onClick={run} disabled={running}>
              {running ? <PulseDot t={{ ...tC, signal: '#fff' }} /> : <span style={{ fontSize: 11 }}>▶</span>} {runLabel}
            </ClickBtn>
            <ClickBtn kind="quiet" size="sm" onClick={reset} disabled={phase === 'idle'}>Reset</ClickBtn>
          </div>
        )}
      </TopBar>

      {screen === 'console' ? (
        <OperationsConsole
          phase={phase} steps={steps} facts={facts} litFacts={litFacts}
          draft={draft} messages={messages} sent={phase === 'sent'}
          draftBody={draftBody} setDraftBody={setDraftBody}
          editing={editing} setEditing={setEditing}
          onApprove={approve} onReject={reject}
        />
      ) : (
        <ProofScreen />
      )}
    </div>
  );
}

const opsRoot = ReactDOM.createRoot(document.getElementById('app'));
opsRoot.render(<OpsApp />);
