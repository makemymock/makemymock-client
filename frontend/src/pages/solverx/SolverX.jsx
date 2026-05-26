import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import MessageBlock from '../../components/solverx/MessageBlock';
import { solverxService } from '../../services/solverxService';
import { parseApiError } from '../../utils/validators';
import styles from './solverx.module.css';

// Top-level mode the student is in. `pill` is the short label shown in
// the composer pill picker (ChatGPT-style), `label`/`sub` populate the
// expanded menu rows.
const MODES = [
  { key: 'solve',  pill: 'Solve',  label: 'Solve a question',   sub: 'Step-by-step reasoning'   },
  { key: 'theory', pill: 'Theory', label: 'Understand a theory', sub: 'Tutor-style explanation' },
];

// Complexity options are mode-dependent. Solve uses Guided/Deep
// (problem-solving register); Theory uses Easy/Deep (explanation
// register). The backend's dispatcher accepts all three values
// (`guided`, `easy`, `deep`) and routes by (mode, complexity).
const COMPLEXITY_BY_MODE = {
  solve: [
    { key: 'guided', pill: 'Guided', label: 'Guided Solve',   sub: 'Fast single-pass solver' },
    { key: 'deep',   pill: 'Deep',   label: 'Deep Reasoning', sub: 'Multi-agent, thorough'   },
  ],
  theory: [
    { key: 'easy',   pill: 'Easy',   label: 'Easy explanation', sub: 'Concise, just the idea'  },
    { key: 'deep',   pill: 'Deep',   label: 'Deep explanation', sub: 'Intuition + derivation + example' },
  ],
};

// Default complexity per mode. Solve defaults to Guided (most users
// just want the answer first); Theory defaults to Deep (theory
// questions usually deserve a real explanation).
const DEFAULT_COMPLEXITY = { solve: 'guided', theory: 'deep' };

const SolverX = () => {
  const [mode, setMode] = useState('solve');
  const [complexity, setComplexity] = useState(DEFAULT_COMPLEXITY.solve);

  // Options shown by the complexity picker swap with the active mode.
  const complexityOptions = useMemo(
    () => COMPLEXITY_BY_MODE[mode] || COMPLEXITY_BY_MODE.solve,
    [mode],
  );

  // Conversations panel — collapsible on every viewport. Defaults to
  // open on desktop (≥900px) and closed on phones so the chat takes
  // the full width on small screens.
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    if (typeof window === 'undefined') return false;
    return window.matchMedia('(min-width: 900px)').matches;
  });
  const [conversations, setConversations] = useState([]);
  const [activeConvId, setActiveConvId] = useState(null);
  // Two-stage delete confirmation: first click arms a conversation
  // (icon turns red + label flips to "Confirm"), second click runs the
  // delete. Clicking anywhere else dismisses the armed state.
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);

  // The transcript of (user/assistant) turns currently displayed.
  const [turns, setTurns] = useState([]);

  // Streaming state for the in-flight assistant turn (only one at a time).
  const [streaming, setStreaming] = useState(null);
  // { phase, statusMessage, topic, insights, blocks: [] }
  const streamCtrlRef = useRef(null);

  const [input, setInput] = useState('');
  // Attached image as a data URL — populated by paste or the file picker.
  // We send it as `image_data_url` on the next submit, then clear it.
  const [attachedImage, setAttachedImage] = useState(null);
  const [attachMenuOpen, setAttachMenuOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const transcriptRef = useRef(null);
  const fileInputRef = useRef(null);
  const cameraInputRef = useRef(null);
  const attachWrapRef = useRef(null);

  // Auto-scroll to the latest content. Re-runs on every render that
  // changes the visible turns/streaming blocks.
  useEffect(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, streaming?.blocks?.length, streaming?.statusMessage]);

  // ---- Load conversation list on mount ----
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await solverxService.listConversations();
        if (!cancelled) setConversations(data.items || []);
      } catch {
        // sidebar is non-critical; ignore errors here
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const refreshConversations = useCallback(async () => {
    try {
      const data = await solverxService.listConversations();
      setConversations(data.items || []);
    } catch { /* ignore */ }
  }, []);

  // Mode-aware setter — swaps complexity to the right default for the
  // new mode (Guided for solve, Deep for theory) AND keeps `deep`
  // sticky if the user was already in deep on the other mode (they
  // probably want depth in both registers).
  const handleModeChange = useCallback((nextMode) => {
    setMode(nextMode);
    setComplexity((prev) => {
      if (prev === 'deep') return 'deep'; // keep deep across modes
      return DEFAULT_COMPLEXITY[nextMode] || 'guided';
    });
  }, []);

  // ---- Switch to a stored conversation ----
  const openConversation = useCallback(async (convId) => {
    setError('');
    setActiveConvId(convId);
    setSidebarOpen(false); // close the mobile drawer
    try {
      const data = await solverxService.getConversation(convId);
      const nextMode = data.mode === 'theory' ? 'theory' : 'solve';
      setMode(nextMode);
      // Align complexity to whatever the last turn of this conversation
      // used; fall back to that mode's default.
      const lastComplexity = [...(data.messages || [])]
        .reverse()
        .find((m) => m.role === 'user' && m.complexity_mode)?.complexity_mode;
      const validForMode = (COMPLEXITY_BY_MODE[nextMode] || []).some(
        (o) => o.key === lastComplexity,
      );
      setComplexity(
        validForMode ? lastComplexity : (DEFAULT_COMPLEXITY[nextMode] || 'guided'),
      );
      // Pair user + assistant messages into "turns". The user message
      // carries the (optional) base64 image we stored on the way in —
      // restoring it here lets the transcript re-render the original
      // screenshot when a saved conversation is reopened.
      const next = [];
      let pending = null;
      for (const msg of data.messages || []) {
        if (msg.role === 'user') {
          pending = {
            question: msg.text,
            complexity: msg.complexity_mode,
            assistant: null,
            imageDataUrl: msg.image_data_url || null,
          };
          next.push(pending);
        } else if (pending && msg.role === 'assistant') {
          pending.assistant = msg;
          pending = null;
        }
      }
      setTurns(next);
    } catch (err) {
      setError(parseApiError(err, 'Could not load conversation.'));
    }
  }, []);

  const startNewConversation = () => {
    streamCtrlRef.current?.abort();
    streamCtrlRef.current = null;
    setActiveConvId(null);
    setTurns([]);
    setStreaming(null);
    setError('');
    setSidebarOpen(false);
  };

  // Two-stage delete: first click arms the row (sets confirmDeleteId);
  // second click on the same row commits. Clicking any other delete
  // button just re-arms to that row; an auto-timeout disarms after 4s.
  const armOrConfirmDelete = useCallback(async (convId, e) => {
    e.stopPropagation();
    if (confirmDeleteId !== convId) {
      setConfirmDeleteId(convId);
      return;
    }
    setConfirmDeleteId(null);
    try {
      await solverxService.deleteConversation(convId);
      setConversations((prev) => prev.filter((c) => c.id !== convId));
      // If the user just nuked the conversation they're viewing,
      // reset back to a blank slate.
      if (activeConvId === convId) {
        streamCtrlRef.current?.abort();
        streamCtrlRef.current = null;
        setActiveConvId(null);
        setTurns([]);
        setStreaming(null);
      }
    } catch (err) {
      setError(parseApiError(err, 'Could not delete that conversation.'));
    }
  }, [confirmDeleteId, activeConvId]);

  // Auto-disarm the confirm state after a short window so an
  // accidentally-armed row doesn't sit there forever.
  useEffect(() => {
    if (!confirmDeleteId) return undefined;
    const t = window.setTimeout(() => setConfirmDeleteId(null), 4000);
    return () => window.clearTimeout(t);
  }, [confirmDeleteId]);

  // ---- Image attach helpers ----

  // Llama 4 Scout caps each image around ~4 MB. Reject early.
  const MAX_IMAGE_BYTES = 4 * 1024 * 1024;

  const fileToDataUrl = (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error || new Error('Could not read file.'));
    reader.readAsDataURL(file);
  });

  const handleImage = async (file) => {
    if (!file) return;
    if (!file.type.startsWith('image/')) {
      setError('Only image files (PNG, JPG, GIF, WEBP) are supported.');
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setError(`Image is too large (${(file.size / 1_000_000).toFixed(1)} MB). Cap is 4 MB.`);
      return;
    }
    try {
      const dataUrl = await fileToDataUrl(file);
      setAttachedImage({ dataUrl, name: file.name || 'pasted-image', size: file.size });
      setError('');
    } catch (err) {
      setError(err.message || 'Could not read that image.');
    }
  };

  const onPaste = (e) => {
    const items = e.clipboardData?.items || [];
    for (const item of items) {
      if (item.kind === 'file' && item.type.startsWith('image/')) {
        const file = item.getAsFile();
        if (file) {
          e.preventDefault();
          handleImage(file);
          return;
        }
      }
    }
  };

  const onFilePick = (e) => {
    const file = e.target.files?.[0];
    handleImage(file);
    e.target.value = ''; // allow re-selecting the same file
    setAttachMenuOpen(false);
  };

  // Close the attach popover when the user clicks anywhere outside it,
  // or presses Escape.
  useEffect(() => {
    if (!attachMenuOpen) return undefined;
    const onDoc = (e) => {
      if (attachWrapRef.current && !attachWrapRef.current.contains(e.target)) {
        setAttachMenuOpen(false);
      }
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setAttachMenuOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [attachMenuOpen]);

  const onTextareaDrop = (e) => {
    const file = e.dataTransfer?.files?.[0];
    if (file && file.type.startsWith('image/')) {
      e.preventDefault();
      handleImage(file);
    }
  };

  // ---- Submit a question ----
  const send = async () => {
    const text = input.trim();
    // Allow image-only submissions when an image is attached. Without an
    // image, a non-empty text is required.
    if (!attachedImage && !text) return;
    if (submitting) return;
    const effectiveText = text || (attachedImage ? 'Solve / explain the attached image.' : '');
    const imageDataUrl = attachedImage?.dataUrl || null;

    setError('');
    setSubmitting(true);
    setInput('');
    setAttachedImage(null);

    // Optimistic user turn
    setTurns((prev) => [
      ...prev,
      {
        question: effectiveText,
        complexity,
        assistant: null,
        pending: true,
        imageDataUrl,
      },
    ]);
    setStreaming({
      phase: 'starting',
      statusMessage: 'Preparing reasoning agents…',
      topic: null,
      insights: [],
      blocks: [],
    });

    const fn = mode === 'theory' ? solverxService.streamTheory : solverxService.streamSolve;
    const { controller, promise } = fn({
      question_text: effectiveText,
      complexity_mode: complexity,
      conversation_id: activeConvId,
      image_data_url: imageDataUrl,
      onEvent: ({ event, data }) => {
        if (event === 'conversation') {
          setActiveConvId(data.conversation_id);
        } else if (event === 'status') {
          setStreaming((s) => s && { ...s, phase: data.phase, statusMessage: data.message });
        } else if (event === 'topic') {
          setStreaming((s) => s && { ...s, topic: data });
        } else if (event === 'insights') {
          setStreaming((s) => s && { ...s, insights: data.items || [] });
        } else if (event === 'block') {
          setStreaming((s) => s && { ...s, blocks: [...s.blocks, data] });
        } else if (event === 'diagram_ready') {
          // A `diagram_pending` placeholder block has finished baking
          // on the backend. If `content` is non-null, swap the
          // placeholder's type to `diagram` and slot the SVG in. If
          // `content` is null (the diagram agent failed or timed out),
          // REMOVE the placeholder so the user doesn't see a permanent
          // "Generating diagram…" spinner.
          setStreaming((s) => {
            if (!s) return s;
            const blocks = s.blocks
              .filter((b) => {
                if (
                  b.type === 'diagram_pending' &&
                  (b.extra?.n ?? null) === data.n
                ) {
                  return !!data.content;
                }
                return true;
              })
              .map((b) => {
                if (
                  b.type === 'diagram_pending' &&
                  (b.extra?.n ?? null) === data.n &&
                  data.content
                ) {
                  return { ...b, type: 'diagram', content: data.content };
                }
                return b;
              });
            return { ...s, blocks };
          });
        } else if (event === 'done') {
          // Commit streaming → permanent turn.
          setStreaming((s) => {
            setTurns((prev) => {
              const copy = [...prev];
              const last = copy[copy.length - 1];
              if (last) {
                last.pending = false;
                last.assistant = {
                  blocks: s?.blocks || [],
                  topic: s?.topic || null,
                  insights: s?.insights || [],
                };
              }
              return copy;
            });
            return null;
          });
          refreshConversations();
        } else if (event === 'error') {
          setError(data.message || 'Something went wrong.');
        }
      },
    });
    streamCtrlRef.current = controller;
    try {
      await promise;
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message || 'Network error while streaming.');
      }
    } finally {
      setSubmitting(false);
      streamCtrlRef.current = null;
    }
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      send();
    }
  };

  const stop = () => {
    streamCtrlRef.current?.abort();
    streamCtrlRef.current = null;
    setSubmitting(false);
    setStreaming(null);
  };

  const placeholderHint = useMemo(() => {
    if (mode === 'theory') {
      return 'Ask a concept — e.g. "Why is the integral of 1/x the natural log?"';
    }
    return 'Paste or type a question — e.g. "Find the equation of the tangent to x² + y² = 25 at (3, 4)."';
  }, [mode]);

  return (
    <div className={`${styles.page} ${sidebarOpen ? styles.pageOpen : ''}`}>
      {/* Backdrop renders only when the mobile drawer is open. Tapping it
          closes the sidebar. Display logic is in CSS — backdrop is a
          no-op on desktop because the sidebar there is in-flow, not a
          drawer. */}
      <div
        className={`${styles.backdrop} ${sidebarOpen ? styles.backdropOn : ''}`}
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />

      {/* ---------- Conversations panel ---------- */}
      <aside
        className={`${styles.sidebar} ${sidebarOpen ? styles.sidebarOpen : ''}`}
        aria-hidden={sidebarOpen ? 'false' : 'true'}
      >
        {/* The inner wrapper keeps content at a fixed 300px so the
            panel can collapse to zero width without re-flowing the
            text inside while the animation runs. */}
        <div className={styles.sidebarInner}>
          <header className={styles.sidebarHeader}>
            <div className={styles.sidebarTitle}>
              <span className={styles.sidebarEyebrow}>SolverX</span>
              <p className={styles.sidebarHead}>Conversations</p>
            </div>
          </header>

          <button type="button" className={styles.newChatBtn} onClick={startNewConversation}>
            + New chat
          </button>

          <div className={styles.convList}>
            {conversations.length === 0 ? (
              <p className={styles.convEmpty}>No conversations yet.</p>
            ) : (
              conversations.map((c) => {
                const isArmed = confirmDeleteId === c.id;
                return (
                  <div
                    key={c.id}
                    className={`${styles.convRow} ${activeConvId === c.id ? styles.convRowActive : ''} ${isArmed ? styles.convRowArmed : ''}`}
                  >
                    <button
                      type="button"
                      className={styles.convItem}
                      onClick={() => openConversation(c.id)}
                      title={c.title}
                    >
                      <span className={styles.convMode}>
                        {c.mode === 'theory' ? 'THEORY' : 'SOLVE'}
                      </span>
                      <span className={styles.convTitle}>{c.title || 'Untitled'}</span>
                      <span className={styles.convPreview}>{c.last_message_preview}</span>
                    </button>
                    <button
                      type="button"
                      className={`${styles.convDelete} ${isArmed ? styles.convDeleteArmed : ''}`}
                      onClick={(e) => armOrConfirmDelete(c.id, e)}
                      aria-label={isArmed ? 'Confirm delete conversation' : 'Delete conversation'}
                      title={isArmed ? 'Click again to confirm' : 'Delete conversation'}
                    >
                      {isArmed ? (
                        <span className={styles.convDeleteText}>Confirm</span>
                      ) : (
                        <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
                             stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                             strokeLinejoin="round" aria-hidden="true">
                          <path d="M3 6h18" />
                          <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                          <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                        </svg>
                      )}
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </aside>

      {/* ---------- Main column ---------- */}
      <main className={styles.main}>
        {/* Thin top strip — only the sidebar toggle lives here now.
            Mode + complexity moved down into the composer (ChatGPT-style)
            so the chat surface stays uncluttered. */}
        <header className={styles.toolbar}>
          <button
            type="button"
            className={styles.menuBtn}
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label={sidebarOpen ? 'Hide conversations' : 'Show conversations'}
            aria-expanded={sidebarOpen}
            title={sidebarOpen ? 'Hide conversations' : 'Show conversations'}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none"
                 stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"
                 strokeLinejoin="round" aria-hidden="true">
              {sidebarOpen ? (
                <path d="M15 6l-6 6 6 6" />
              ) : (
                <path d="M9 6l6 6-6 6" />
              )}
            </svg>
          </button>
          <span className={styles.toolbarTitle}>SolverX</span>
        </header>

        {/* Transcript */}
        <section ref={transcriptRef} className={styles.transcript}>
          {turns.length === 0 && !streaming ? (
            <EmptyState mode={mode} />
          ) : null}

          {turns.map((turn, i) => (
            <TurnView
              key={i}
              turn={turn}
              streaming={i === turns.length - 1 && streaming ? streaming : null}
            />
          ))}
        </section>

        {/* Error banner */}
        {error ? (
          <div className={styles.errorBanner} role="alert">{error}</div>
        ) : null}

        {/* Composer */}
        <footer className={styles.composer}>
          {attachedImage ? (
            <div className={styles.attachedRow}>
              <img
                src={attachedImage.dataUrl}
                alt={attachedImage.name}
                className={styles.attachedThumb}
              />
              <div className={styles.attachedMeta}>
                <p className={styles.attachedName}>{attachedImage.name}</p>
                <p className={styles.attachedSize}>
                  {(attachedImage.size / 1024).toFixed(0)} KB · attached
                </p>
              </div>
              <button
                type="button"
                className={styles.attachedRemove}
                onClick={() => setAttachedImage(null)}
                aria-label="Remove image"
              >
                ✕
              </button>
            </div>
          ) : null}

          <textarea
            className={styles.input}
            placeholder={placeholderHint}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            onPaste={onPaste}
            onDrop={onTextareaDrop}
            onDragOver={(e) => e.preventDefault()}
            rows={3}
            disabled={submitting}
          />

          {/* Two hidden inputs — same `handleImage` pipeline. The second
              one carries `capture="environment"`, which tells mobile
              browsers to open the rear camera directly instead of the
              gallery. Desktop browsers ignore `capture` and fall back to
              the standard file picker. */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            onChange={onFilePick}
            style={{ display: 'none' }}
          />
          <input
            ref={cameraInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            onChange={onFilePick}
            style={{ display: 'none' }}
          />

          <div className={styles.composerActions}>
            <div className={styles.composerLeft}>
              <div className={styles.attachWrap} ref={attachWrapRef}>
                <button
                  type="button"
                  className={styles.attachBtn}
                  onClick={() => setAttachMenuOpen((v) => !v)}
                  disabled={submitting}
                  aria-haspopup="menu"
                  aria-expanded={attachMenuOpen}
                  title="Attach image (or paste with Ctrl+V)"
                >
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
                       stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                       strokeLinejoin="round" aria-hidden="true">
                    <path d="M21.4 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                  </svg>
                  <span>Attach</span>
                </button>

                {attachMenuOpen ? (
                  <div className={styles.attachMenu} role="menu">
                    <button
                      type="button"
                      role="menuitem"
                      className={styles.attachMenuItem}
                      onClick={() => {
                        setAttachMenuOpen(false);
                        fileInputRef.current?.click();
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="16" height="16" fill="none"
                           stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                           strokeLinejoin="round" aria-hidden="true">
                        <rect x="3" y="3" width="18" height="18" rx="2" />
                        <circle cx="9" cy="9" r="2" />
                        <path d="M21 15l-5-5L5 21" />
                      </svg>
                      <span>Choose photo</span>
                    </button>
                    <button
                      type="button"
                      role="menuitem"
                      className={styles.attachMenuItem}
                      onClick={() => {
                        setAttachMenuOpen(false);
                        cameraInputRef.current?.click();
                      }}
                    >
                      <svg viewBox="0 0 24 24" width="16" height="16" fill="none"
                           stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                           strokeLinejoin="round" aria-hidden="true">
                        <path d="M3 7h4l2-2h6l2 2h4v12H3z" />
                        <circle cx="12" cy="13" r="3.5" />
                      </svg>
                      <span>Take photo</span>
                    </button>
                  </div>
                ) : null}
              </div>

              <PickerPill
                ariaLabel="SolverX mode"
                options={MODES}
                value={mode}
                onChange={handleModeChange}
                disabled={submitting}
                icon={(
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
                       stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                       strokeLinejoin="round" aria-hidden="true">
                    <path d="M13 2L4 14h7l-1 8 9-12h-7z" />
                  </svg>
                )}
              />

              <PickerPill
                ariaLabel={mode === 'theory' ? 'Explanation depth' : 'Reasoning depth'}
                options={complexityOptions}
                value={complexity}
                onChange={setComplexity}
                disabled={submitting}
                icon={(
                  <svg viewBox="0 0 24 24" width="14" height="14" fill="none"
                       stroke="currentColor" strokeWidth="2" strokeLinecap="round"
                       strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="9" />
                    <path d="M12 7v5l3 2" />
                  </svg>
                )}
              />
            </div>
            {submitting ? (
              <button type="button" className={styles.stopBtn} onClick={stop}>
                ◼ Stop
              </button>
            ) : (
              <button
                type="button"
                className={styles.sendBtn}
                onClick={send}
                disabled={!input.trim() && !attachedImage}
              >
                Send →
              </button>
            )}
          </div>
        </footer>
      </main>
    </div>
  );
};

// ----------------------------------------------------------------------------
// Sub-components
// ----------------------------------------------------------------------------

// Compact ChatGPT-style picker — shows the current selection as a
// rounded pill; click opens a small menu above with full label + sub.
const PickerPill = ({ ariaLabel, options, value, onChange, disabled, icon }) => {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const current = options.find((o) => o.key === value) || options[0];

  return (
    <div className={styles.pickerWrap} ref={wrapRef}>
      <button
        type="button"
        className={`${styles.pickerBtn} ${open ? styles.pickerBtnOn : ''}`}
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={ariaLabel}
        title={current.label}
      >
        <span className={styles.pickerIcon}>{icon}</span>
        <span className={styles.pickerLabel}>{current.pill}</span>
        <svg viewBox="0 0 24 24" width="10" height="10" fill="none"
             stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"
             strokeLinejoin="round" aria-hidden="true"
             className={styles.pickerChevron}>
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open ? (
        <div className={styles.pickerMenu} role="menu">
          {options.map((o) => (
            <button
              key={o.key}
              type="button"
              role="menuitemradio"
              aria-checked={o.key === value}
              className={`${styles.pickerItem} ${o.key === value ? styles.pickerItemActive : ''}`}
              onClick={() => {
                onChange(o.key);
                setOpen(false);
              }}
            >
              <span className={styles.pickerItemLabel}>{o.label}</span>
              <span className={styles.pickerItemSub}>{o.sub}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
};

const EmptyState = ({ mode }) => (
  <div className={styles.empty}>
    <span className={styles.emptyBadge}>SolverX · multi-agent</span>
    <h2 className={styles.emptyTitle}>
      {mode === 'theory' ? 'Ask a concept.' : 'Drop your toughest question.'}
    </h2>
    <p className={styles.emptySub}>
      {mode === 'theory'
        ? 'A tutor that breaks ideas down with intuition, examples, and the formal definition.'
        : 'Step-by-step reasoning that flags traps and lands a clean final answer.'}
    </p>
    <div className={styles.emptyChips}>
      <span className={styles.emptyChip}>
        <span className={styles.emptyChipDot} aria-hidden="true" />
        {mode === 'theory' ? 'Intuition first' : 'Step-by-step'}
      </span>
      <span className={styles.emptyChip}>
        <span className={styles.emptyChipDot} aria-hidden="true" />
        {mode === 'theory' ? 'Worked example' : 'Spots traps'}
      </span>
      <span className={styles.emptyChip}>
        <span className={styles.emptyChipDot} aria-hidden="true" />
        {mode === 'theory' ? 'Formal definition' : 'Clean final answer'}
      </span>
    </div>
  </div>
);

const TurnView = ({ turn, streaming }) => {
  return (
    <div className={styles.turn}>
      <div className={styles.userBubble}>
        <span className={styles.userTag}>You</span>
        {turn.imageDataUrl ? (
          <img
            src={turn.imageDataUrl}
            alt="Attached question"
            className={styles.userImage}
          />
        ) : null}
        <p>{turn.question}</p>
      </div>

      {streaming ? (
        <AssistantStreamingView streaming={streaming} />
      ) : turn.assistant ? (
        <AssistantFinalView assistant={turn.assistant} />
      ) : null}
    </div>
  );
};

const AssistantStreamingView = ({ streaming }) => (
  <div className={styles.assistant}>
    <div className={styles.statusRow}>
      <span className={styles.spinner} aria-hidden="true" />
      <span className={styles.statusText}>{streaming.statusMessage}</span>
    </div>

    {streaming.topic ? <TopicPills topic={streaming.topic} /> : null}
    {streaming.insights?.length ? <InsightList items={streaming.insights} /> : null}

    <div className={styles.blocks}>
      {streaming.blocks.map((b, i) => (
        <MessageBlock
          key={i}
          block={b}
          index={b.type === 'step' ? streaming.blocks.filter((x, j) => j <= i && x.type === 'step').length : null}
        />
      ))}
    </div>
  </div>
);

const AssistantFinalView = ({ assistant }) => {
  const blocks = assistant.blocks || [];
  let stepCount = 0;
  return (
    <div className={styles.assistant}>
      {assistant.topic ? <TopicPills topic={assistant.topic} /> : null}
      {assistant.insights?.length ? <InsightList items={assistant.insights} /> : null}

      <div className={styles.blocks}>
        {blocks.map((b, i) => {
          if (b.type === 'step') stepCount += 1;
          return (
            <MessageBlock
              key={i}
              block={b}
              index={b.type === 'step' ? stepCount : null}
            />
          );
        })}
      </div>
    </div>
  );
};

const TopicPills = ({ topic }) => {
  const labels = [topic.subject, topic.chapter, topic.topic, topic.subtopic]
    .filter(Boolean);
  if (labels.length === 0 && !topic.difficulty) return null;
  return (
    <div className={styles.topicRow}>
      {labels.map((l, i) => (
        <span key={i} className={styles.topicPill}>{l}</span>
      ))}
      {topic.difficulty ? (
        <span className={`${styles.topicPill} ${styles[`diff_${topic.difficulty}`] || ''}`}>
          {topic.difficulty}
        </span>
      ) : null}
    </div>
  );
};

const InsightList = ({ items }) => (
  <div className={styles.insightStack}>
    {items.map((it, i) => (
      <div key={i} className={styles.insight}>
        <p className={styles.insightHead}>{it.headline}</p>
        <p className={styles.insightDetail}>{it.detail}</p>
      </div>
    ))}
  </div>
);

export default SolverX;
