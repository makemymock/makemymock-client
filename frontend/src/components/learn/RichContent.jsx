import { useMemo } from 'react';
import katex from 'katex';
import styles from './RichContent.module.css';

// jee_mains_pyqs content is HTML (with <br>, <img>, <sup>) that embeds LaTeX in
// $$…$$ / $…$ / \(…\) / \[…\] delimiters. MarkdownText only does markdown+math,
// not raw HTML, so this renderer splits out the math, hands each piece to KaTeX,
// and keeps the surrounding exam HTML for images / superscripts / line breaks.

// Same macro set MarkdownText feeds rehype-katex, so equations render
// identically across the app.
const KATEX_MACROS = {
  '\\norm': '\\lVert #1 \\rVert',
  '\\abs': '\\lvert #1 \\rvert',
  '\\set': '\\{#1\\}',
  '\\inner': '\\langle #1, #2 \\rangle',
  '\\paren': '\\left( #1 \\right)',
  '\\R': '\\mathbb{R}',
  '\\N': '\\mathbb{N}',
  '\\Z': '\\mathbb{Z}',
  '\\Q': '\\mathbb{Q}',
  '\\C': '\\mathbb{C}',
  '\\d': '\\mathrm{d}',
  '\\deg': '^{\\circ}',
};

// Ordered so $$…$$ wins over $…$ and the TeX bracket forms are caught whole.
const MATH_RE = /\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|\$[^$\n]+?\$/g;

// examgoal encodes the relations < and > as \< and \> (and occasionally as HTML
// entities). KaTeX rejects those, so the whole formula renders in errorColor red
// — which is exactly the "broken LaTeX" you see. Normalise these known quirks
// before handing the TeX to KaTeX. Deterministic + instant; no AI needed.
function fixExamTex(tex) {
  return tex
    .replace(/\\</g, '<')
    .replace(/\\>/g, '>')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&');
}

function renderMath(tex, displayMode) {
  try {
    return katex.renderToString(fixExamTex(tex), {
      displayMode,
      throwOnError: false,   // a bad formula renders in red, doesn't blank the page
      errorColor: '#ef4444',
      strict: 'ignore',
      macros: KATEX_MACROS,
    });
  } catch {
    return '';
  }
}

// The content is first-party exam data, but strip scripts / inline handlers as
// defence-in-depth before it reaches dangerouslySetInnerHTML.
function scrubHtml(html) {
  return String(html)
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, '')
    .replace(/javascript:/gi, '');
}

function toHtml(raw, blockMath) {
  if (!raw) return '';
  let out = '';
  let last = 0;
  const re = new RegExp(MATH_RE);
  let m;
  while ((m = re.exec(raw)) !== null) {
    out += scrubHtml(raw.slice(last, m.index));
    const tok = m[0];
    let tex;
    let display;
    if (tok.startsWith('$$')) {
      tex = tok.slice(2, -2);
      display = blockMath;
    } else if (tok.startsWith('\\[')) {
      tex = tok.slice(2, -2);
      display = blockMath;
    } else if (tok.startsWith('\\(')) {
      tex = tok.slice(2, -2);
      display = false;
    } else {
      tex = tok.slice(1, -1);   // $…$
      display = false;
    }
    out += renderMath(tex.trim(), display);
    last = m.index + tok.length;
  }
  out += scrubHtml(raw.slice(last));
  return out;
}

/**
 * Render exam HTML + LaTeX.
 *   block=true  → $$…$$ / \[…\] render as centered display math (questions,
 *                 explanations).
 *   block=false → all math inline (option labels — examgoal wraps even a bare
 *                 "4" in $$…$$, which shouldn't become a centered block).
 */
const RichContent = ({ html, block = true, className = '' }) => {
  const rendered = useMemo(() => toHtml(html, block), [html, block]);
  if (!rendered) return null;
  const Tag = block ? 'div' : 'span';
  return (
    <Tag
      className={`${styles.rich} ${className}`}
      dangerouslySetInnerHTML={{ __html: rendered }}
    />
  );
};

export default RichContent;
