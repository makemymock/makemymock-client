import { memo, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import styles from './MarkdownText.module.css';

// Macros KaTeX doesn't ship out of the box but that the LLM (and many
// textbook sources) treat as standard. Each entry uses `#1`/`#2` as
// positional arguments. If the model writes `\norm{a \times b}` we
// expand it to `\lVert a \times b \rVert` before KaTeX renders it.
const KATEX_MACROS = {
  '\\norm': '\\lVert #1 \\rVert',
  '\\abs': '\\lvert #1 \\rvert',
  '\\set': '\\{#1\\}',
  '\\inner': '\\langle #1, #2 \\rangle',
  '\\paren': '\\left( #1 \\right)',
  '\\bra': '\\langle #1 \\rvert',
  '\\ket': '\\lvert #1 \\rangle',
  '\\R': '\\mathbb{R}',
  '\\N': '\\mathbb{N}',
  '\\Z': '\\mathbb{Z}',
  '\\Q': '\\mathbb{Q}',
  '\\C': '\\mathbb{C}',
  '\\d': '\\mathrm{d}',          // for `dx` in integrals
  '\\deg': '^{\\circ}',          // 90\deg → 90°
};

const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [
  [rehypeKatex, {
    macros: KATEX_MACROS,
    // `throwOnError: false` so a single broken formula doesn't blank
    // the whole solution — KaTeX renders the offending source in red
    // and continues with the rest.
    throwOnError: false,
    errorColor: '#ef4444',
    strict: 'ignore',
  }],
];

// Some bbd_db rows store LaTeX with single-dollar inline (`$x^2$`) and
// double-dollar block (`$$...$$`), others use \( ... \) and \[ ... \].
// remark-math's default delimiters are $ / $$ and \( / \[, so all those
// styles render out of the box.
//
// SolverX agents occasionally drift to plain-bracket math like
//   [3 = \frac{1 \cdot 2 + x \cdot 1}{1+2}]
// which remark-math doesn't recognise — markdown then treats it as the
// start of a link and the LaTeX leaks through as raw text. We patch
// those up before handing the markdown to ReactMarkdown.

// `[ ... ]` whose payload contains at least one `\command`, and which is
// NOT immediately followed by `(` (so real markdown links are spared).
// `[^\[\]]` is lenient with newlines so multi-line block math survives.
const BRACKET_MATH_RE = /\[([^\[\]]*?\\[a-zA-Z][^\[\]]*?)\](?!\()/g;

// Same deal for parenthesised inline math like  ( a + b = \pi/2 ).
// Restricted further than the bracket variant: payload must be short
// (≤ 60 chars) AND start with a non-letter, to avoid catching prose
// like "(see the diagram for \\Delta)" or natural-language parentheses.
const PAREN_MATH_RE = /(?<![\w$])\(\s*([^()\n]{0,60}?\\[a-zA-Z][^()\n]{0,60}?)\s*\)/g;

function normalize(text) {
  if (text == null) return '';
  let s = String(text).replace(/\r\n?/g, '\n');

  // Bracket block-math → $$ ... $$. The replacement uses `$$$$` to emit
  // a literal `$$` (each `$$` in a replacement string evaluates to `$`).
  s = s.replace(BRACKET_MATH_RE, (_m, inner) => `$$${inner.trim()}$$`);

  // Parenthesised inline math → $...$. Skipped when preceded by a word
  // character or another `$` to avoid breaking `f(x)` or `$5 (USD)`.
  s = s.replace(PAREN_MATH_RE, (_m, inner) => `$${inner.trim()}$`);

  return s;
}

const MarkdownText = ({ text, inline = false, className = '' }) => {
  const value = useMemo(() => normalize(text), [text]);
  if (!value) return null;
  const Tag = inline ? 'span' : 'div';
  return (
    <Tag className={`${styles.root} ${inline ? styles.inline : ''} ${className}`}>
      <ReactMarkdown
        remarkPlugins={REMARK_PLUGINS}
        rehypePlugins={REHYPE_PLUGINS}
        components={inline ? INLINE_COMPONENTS : undefined}
      >
        {value}
      </ReactMarkdown>
    </Tag>
  );
};

// In inline contexts (option labels, matching cells) we want to flatten
// paragraphs so the text doesn't generate <p> blocks with margins.
const INLINE_COMPONENTS = {
  p: ({ children }) => <>{children}</>,
};

export default memo(MarkdownText);
