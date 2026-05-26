import React, { useMemo, useRef } from 'react';
import MarkdownText from '../common/MarkdownText/MarkdownText';
import styles from './MessageBlock.module.css';

// Human-readable labels for the bracket block types the backend emits.
const TYPE_META = {
  understanding:    { label: 'Problem understanding', accent: 'blue' },
  key_concept:      { label: 'Key concept',           accent: 'teal' },
  step:             { label: 'Step',                  accent: 'teal' },
  intuition:        { label: 'Intuition',             accent: 'purple' },
  warning:          { label: 'Common mistake',        accent: 'red' },
  diagram:          { label: 'Diagram',               accent: 'gold' },
  diagram_pending:  { label: 'Diagram',               accent: 'gold' },
  final_answer:     { label: 'Final answer',          accent: 'green' },
  alternative:      { label: 'Alternative approach',  accent: 'purple' },
  summary:          { label: 'Revision summary',      accent: 'blue' },
  insight:          { label: 'Insight',               accent: 'gold' },
};

// ---------------------------------------------------------------------------
// Diagram handling — two formats supported:
//   1. TikZ  (current pipeline) → rendered client-side by TikZJax.
//      Detected by the presence of `\begin{tikzpicture}`.
//   2. SVG   (legacy, pre-TikZ pipeline) → rendered via sanitised
//      innerHTML. Kept so old conversations still render.
// ---------------------------------------------------------------------------

// Strip an enclosing ```code fence``` if present.
function stripFence(raw) {
  if (!raw) return raw;
  const m = raw.match(/^```(?:svg|html|xml|latex|tex|tikz)?\s*\n([\s\S]*?)\n```\s*$/i);
  return m ? m[1] : raw;
}

// Pull the first `\begin{tikzpicture}…\end{tikzpicture}` block out of
// the content. Returns null if no valid TikZ environment is found.
function extractTikz(raw) {
  if (!raw) return null;
  const cleaned = stripFence(raw.trim());
  const m = cleaned.match(/\\begin\{tikzpicture\}[\s\S]*?\\end\{tikzpicture\}/);
  return m ? m[0] : null;
}

// Legacy SVG extractor. Kept so old saved conversations still render.
function extractSvg(raw) {
  if (!raw) return null;
  const cleaned = stripFence(raw.trim());
  const start = cleaned.search(/<svg\b/i);
  if (start === -1) return null;
  const end = cleaned.toLowerCase().lastIndexOf('</svg>');
  if (end === -1) return null;
  return cleaned.slice(start, end + 6);
}

// Tags whose presence is incompatible with safe SVG embedding.
const DANGEROUS_TAGS = new Set([
  'script', 'foreignobject', 'iframe', 'audio', 'video', 'object',
  'embed', 'source', 'link', 'meta', 'style', 'animate', 'set',
  'animatetransform', 'animatemotion', 'handler',
]);

function sanitizeNode(el) {
  // Recurse first so we can drop dangerous children before they touch innerHTML.
  Array.from(el.children).forEach((child) => {
    if (DANGEROUS_TAGS.has(child.tagName.toLowerCase())) {
      child.remove();
      return;
    }
    sanitizeNode(child);
  });

  // Strip every event handler and javascript: / non-image data: URL.
  Array.from(el.attributes || []).forEach((attr) => {
    const name = attr.name.toLowerCase();
    const value = String(attr.value || '').trim().toLowerCase();
    if (name.startsWith('on')) {
      el.removeAttribute(attr.name);
    } else if ((name === 'href' || name === 'xlink:href') && (
      value.startsWith('javascript:') ||
      (value.startsWith('data:') && !value.startsWith('data:image/'))
    )) {
      el.removeAttribute(attr.name);
    }
  });
}

function sanitizeSvg(svgString) {
  try {
    const parser = new DOMParser();
    const doc = parser.parseFromString(svgString, 'image/svg+xml');
    if (doc.querySelector('parsererror')) return null;
    const root = doc.documentElement;
    if (!root || root.tagName.toLowerCase() !== 'svg') return null;
    sanitizeNode(root);
    // Ensure responsive scaling: viewBox must exist; pixel width/height removed.
    if (!root.getAttribute('viewBox')) {
      const w = root.getAttribute('width') || '400';
      const h = root.getAttribute('height') || '280';
      root.setAttribute('viewBox', `0 0 ${parseFloat(w) || 400} ${parseFloat(h) || 280}`);
    }
    root.removeAttribute('width');
    root.removeAttribute('height');
    return new XMLSerializer().serializeToString(root);
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// TikZ rendering — iframe approach.
//
// TikZJax v1 only scans the DOM for `<script type="text/tikz">` tags on
// its own `DOMContentLoaded`. It has no MutationObserver and exposes no
// public process API — so dynamically injecting a script tag into the
// main document after page load NEVER triggers rendering.
//
// Workaround: render each figure inside its own `<iframe srcdoc=...>`.
// Each iframe has an independent document lifecycle, so TikZJax loads,
// fires on the iframe's own DOMContentLoaded, finds the script tag in
// the iframe's initial HTML, and processes it. Reliable on every render.
//
// The iframe auto-resizes to its content height via the `onLoad`
// callback (same-origin srcdoc means we can read `contentDocument`).
// Theme adaptation happens via the parent CSS filtering: an `invert`
// rule on `.tikzFrame` in dark mode flips black ink to near-white.
// ---------------------------------------------------------------------------

// Escape any closing `</script>` sequence inside the TikZ source so the
// embedded `<script type="text/tikz">` tag isn't truncated. TikZ should
// never contain that string, but defensive coding.
const escapeForScript = (s) => (s || '').replace(/<\/(script)/gi, '<\\/$1');

const buildTikzSrcDoc = (tikz) => `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<link rel="stylesheet" href="https://tikzjax.com/v1/fonts.css" />
<script src="https://tikzjax.com/v1/tikzjax.js"></script>
<style>
  /* No fixed height / no overflow clipping — let the body grow so the
     parent can measure the natural figure size after TikZJax renders. */
  html, body {
    margin: 0;
    padding: 14px;
    background: transparent;
    color: #000;
    font-family: serif;
  }
  body {
    text-align: center;
    /* Avoid horizontal scrollbars on the iframe — TikZJax's SVG will
       naturally fit width because the figure is centred. */
    overflow-x: hidden;
  }
  svg {
    display: inline-block;
    max-width: 100%;
    height: auto;
  }
</style>
</head>
<body>
<script type="text/tikz" data-show-console="true">
${escapeForScript(tikz)}
</script>
</body>
</html>`;

const TikzFigure = ({ tikz }) => {
  const iframeRef = useRef(null);
  const srcDoc = useMemo(() => buildTikzSrcDoc(tikz), [tikz]);

  // Resize the iframe to match the rendered figure. We try a few signals
  // in order of accuracy:
  //   1. The bounding rect of the <svg> element TikZJax produced — most
  //      accurate, includes any decoration.
  //   2. body.scrollHeight — catches the figure plus padding even if
  //      the SVG measurement fails.
  //   3. documentElement.scrollHeight — last-ditch fallback.
  // We poll for ~3 seconds because TikZJax compiles via WASM and the
  // final SVG sometimes appears a moment after onLoad fires.
  const resize = () => {
    const frame = iframeRef.current;
    if (!frame) return 0;
    try {
      const doc = frame.contentDocument;
      if (!doc) return 0;

      const svg = doc.querySelector('svg');
      let h = 0;
      if (svg) {
        const rect = svg.getBoundingClientRect();
        if (rect && rect.height > 0) {
          // SVG height + the 14px top/bottom padding we set in srcdoc.
          h = Math.ceil(rect.height) + 28;
        }
      }
      if (!h) {
        h = Math.max(
          doc.documentElement?.scrollHeight ?? 0,
          doc.body?.scrollHeight ?? 0,
        );
      }
      if (h > 0) frame.style.height = `${h}px`;
      return h;
    } catch {
      return 0;
    }
  };

  return (
    <iframe
      ref={iframeRef}
      srcDoc={srcDoc}
      className={styles.tikzFrame}
      onLoad={() => {
        resize();
        // TikZJax finishes asynchronously after onLoad fires. Poll for
        // up to ~3 s and settle on the final height. Stop polling as
        // soon as two consecutive measurements agree — that means the
        // figure has finished growing.
        const start = performance.now();
        let lastH = 0;
        let stableCount = 0;
        const tick = () => {
          const h = resize();
          if (h > 0 && h === lastH) {
            stableCount += 1;
            if (stableCount >= 2) return; // settled
          } else {
            stableCount = 0;
          }
          lastH = h;
          if (performance.now() - start < 3000) {
            window.setTimeout(tick, 150);
          }
        };
        window.setTimeout(tick, 150);
      }}
      sandbox="allow-scripts allow-same-origin"
      title="TikZ diagram"
    />
  );
};


// ---------------------------------------------------------------------------

const MessageBlock = ({ block, index }) => {
  const meta = TYPE_META[block.type] || { label: block.type, accent: 'teal' };
  const isStep = block.type === 'step';
  const isDiagram = block.type === 'diagram';
  const isDiagramPending = block.type === 'diagram_pending';
  // Pull the diagram description from the placeholder so we can show
  // the student what's being drawn while the agents work.
  const pendingDescription = isDiagramPending
    ? (block.extra?.description || block.content || '').trim()
    : '';

  // Prefer TikZ (current pipeline); fall back to SVG (legacy saved
  // conversations from before the TikZ switch).
  const tikz = useMemo(
    () => (isDiagram ? extractTikz(block.content) : null),
    [isDiagram, block.content],
  );
  const sanitizedSvg = useMemo(
    () => (isDiagram && !tikz ? sanitizeSvg(extractSvg(block.content) || '') : null),
    [isDiagram, tikz, block.content],
  );

  return (
    <section
      className={`${styles.block} ${styles[`accent_${meta.accent}`] || ''} ${
        isStep ? styles.stepBlock : ''
      }`}
    >
      <header className={styles.header}>
        <span className={styles.tag}>{meta.label}</span>
        {block.title ? <h3 className={styles.title}>{block.title}</h3> : null}
        {isStep && index != null ? (
          <span className={styles.stepIndex}>#{index}</span>
        ) : null}
      </header>

      {isDiagramPending ? (
        // Placeholder shown while the diagram agents (draft + polish)
        // run in parallel with the rest of the solve stream. Swapped
        // out by the parent when a `diagram_ready` SSE event arrives —
        // at that point this block's `type` flips to `diagram`.
        <div className={styles.diagramPending}>
          <span className={styles.diagramSpinner} aria-hidden="true" />
          <div className={styles.diagramPendingText}>
            <p className={styles.diagramPendingTitle}>Generating diagram…</p>
            {pendingDescription ? (
              <p className={styles.diagramPendingDescription}>
                {pendingDescription}
              </p>
            ) : null}
          </div>
        </div>
      ) : isDiagram ? (
        tikz ? (
          // Current pipeline — TikZJax renders the figure to inline SVG
          // client-side. `key={tikz}` forces a remount when the content
          // changes (e.g. when the diagram_ready event flips the block
          // type from `diagram_pending` to `diagram`), which retriggers
          // the script-tag injection inside TikzFigure.
          <div className={styles.diagramSvg}>
            <TikzFigure key={tikz} tikz={tikz} />
          </div>
        ) : sanitizedSvg ? (
          // Legacy SVG — sanitised, then injected via innerHTML.
          <div
            className={styles.diagramSvg}
            dangerouslySetInnerHTML={{ __html: sanitizedSvg }}
          />
        ) : (
          // Un-parseable content — show the source as a fallback so
          // nothing is silently lost.
          <pre className={styles.diagram}>
            <code>{block.content}</code>
          </pre>
        )
      ) : (
        <div className={styles.body}>
          <MarkdownText text={block.content || ''} />
        </div>
      )}
    </section>
  );
};

export default MessageBlock;
