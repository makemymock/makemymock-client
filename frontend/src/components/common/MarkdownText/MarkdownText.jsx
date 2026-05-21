import { memo, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import styles from './MarkdownText.module.css';

const REMARK_PLUGINS = [remarkGfm, remarkMath];
const REHYPE_PLUGINS = [rehypeKatex];

// Some bbd_db rows store LaTeX with single-dollar inline (`$x^2$`) and
// double-dollar block (`$$...$$`), others use \( ... \) and \[ ... \].
// remark-math's default delimiters are $ / $$ and \( / \[, so both styles
// work out of the box. We also normalise stray Windows newlines so the
// renderer's hard-break rules behave.
function normalize(text) {
  if (text == null) return '';
  const s = String(text);
  // Convert literal `\n` sequences from bad copy-paste into real newlines.
  // Avoid touching `\\n` (escaped newline in LaTeX), so we only replace
  // `\n` that's not preceded by another backslash.
  return s.replace(/\r\n?/g, '\n');
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
