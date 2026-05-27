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

function normalize(text) {
  if (text == null) return '';
  return String(text).replace(/\r\n?/g, '\n');
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
