import React, { useMemo } from 'react';
import MarkdownText from '../common/MarkdownText/MarkdownText';
import styles from './MessageBlock.module.css';

// Human-readable labels for the bracket block types the backend emits.
const TYPE_META = {
  understanding: { label: 'Problem understanding', accent: 'blue' },
  key_concept:   { label: 'Key concept',           accent: 'teal' },
  step:          { label: 'Step',                  accent: 'teal' },
  intuition:     { label: 'Intuition',             accent: 'purple' },
  warning:       { label: 'Common mistake',        accent: 'red' },
  diagram:       { label: 'Diagram',               accent: 'gold' },
  final_answer:  { label: 'Final answer',          accent: 'green' },
  alternative:   { label: 'Alternative approach',  accent: 'purple' },
  summary:       { label: 'Revision summary',      accent: 'blue' },
  insight:       { label: 'Insight',               accent: 'gold' },
};

// ---------------------------------------------------------------------------
// SVG handling
// ---------------------------------------------------------------------------

// Strip an enclosing ```svg ... ``` (or ```html / ```xml) fence if present.
function stripFence(raw) {
  if (!raw) return raw;
  const m = raw.match(/^```(?:svg|html|xml)?\s*\n([\s\S]*?)\n```\s*$/i);
  return m ? m[1] : raw;
}

// Extract the first <svg>…</svg> in the block body. The model is told to
// emit raw SVG but occasionally adds a sentence of preamble or a stray
// fence — pull defensively.
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

const MessageBlock = ({ block, index }) => {
  const meta = TYPE_META[block.type] || { label: block.type, accent: 'teal' };
  const isStep = block.type === 'step';
  const isDiagram = block.type === 'diagram';

  const sanitizedSvg = useMemo(
    () => (isDiagram ? sanitizeSvg(extractSvg(block.content) || '') : null),
    [isDiagram, block.content],
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

      {isDiagram ? (
        sanitizedSvg ? (
          <div
            className={styles.diagramSvg}
            // The SVG passed through `sanitizeSvg` above — script tags,
            // foreignObject, event handlers, and external resources are
            // stripped, so this innerHTML is safe.
            dangerouslySetInnerHTML={{ __html: sanitizedSvg }}
          />
        ) : (
          // Legacy / un-parseable content (e.g. old TikZ conversations) —
          // fall back to showing the source as a code block.
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
