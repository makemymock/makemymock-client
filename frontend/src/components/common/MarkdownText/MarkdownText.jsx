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

// `|...|` (single bars) or `|...|^n` whose interior contains a LaTeX
// command — wrap the whole thing in $...$. The LLM occasionally writes
// `|\vec{a} + \vec{b}|^2 = ...` outside math delimiters; the bars and
// `\vec` then leak out as plain text.
const PIPE_MATH_RE = /(?<![\w$|])\|([^|\n$]*\\[a-zA-Z][^|\n$]*)\|(\^\{?[\w\d\s+\-*/]*\}?)?/g;

// `||...||` with a backslash command inside — usually intended as a
// norm \| ... \|. Replace with `$\| ... \|$`. (e.g. `||a×\vec{a}+\vec{b}||`)
const DOUBLE_PIPE_MATH_RE = /\|\|([^|\n$]*\\[a-zA-Z][^|\n$]*)\|\|/g;

// ---------------------------------------------------------------------------
// Per-line math-span unifier.
//
// The LLM keeps emitting fragmented math on a single line, e.g.
//   "Integrate both sides: \int $$\frac{1}{y^3} + y$$ dy = \int (e^{4x} +
//    e^{-x}) dx. This yields …"
// where the bare `\int`, the trailing `dy`, and the `(e^{4x} + e^{-x}) dx`
// all leak as plain text because they live outside `$...$`. Per-line
// unification finds every math anchor (a `$..$` chunk or a bare `\cmd`)
// on the line, walks the "glue" between them — whitespace, operators,
// digits, parens, short identifiers like `dx`/`dy` — and if no long
// English word appears in that glue, merges the whole span into one
// `$...$` (stripping any nested `$` markers).
//
// Spans are bounded by sentence boundaries (`. ` followed by a capital
// letter) and 4+ letter prose words, so untouched prose stays intact.
// ---------------------------------------------------------------------------

const MATH_REGION_RE = /\${1,2}[^$\n]+?\${1,2}/g;
const BARE_CMD_RE = /\\[a-zA-Z]+(?:\{[^{}\n]*\})*/g;
// Glue characters that connect math tokens without being prose.
const GLUE_CHAR_RE = /[\s+\-=*/^_,()|{}[\]]/;

function unifyBrokenMathLine(line) {
  // Cheap rejects: code blocks, no backslash at all → no work needed.
  if (line.length === 0 || line.indexOf('\\') === -1) return line;
  if (/^(\s{4,}|```)/.test(line)) return line;

  // 1) Find every `$..$` / `$$..$$` chunk on this line.
  const mathChunks = [];
  let mm;
  MATH_REGION_RE.lastIndex = 0;
  while ((mm = MATH_REGION_RE.exec(line)) !== null) {
    mathChunks.push({ start: mm.index, end: MATH_REGION_RE.lastIndex });
  }
  const inMath = (i) => mathChunks.some((c) => i >= c.start && i < c.end);

  // 2) Find every bare `\cmd{args}*` that's NOT already inside a math chunk.
  const bareCmds = [];
  BARE_CMD_RE.lastIndex = 0;
  while ((mm = BARE_CMD_RE.exec(line)) !== null) {
    if (!inMath(mm.index)) {
      bareCmds.push({ start: mm.index, end: BARE_CMD_RE.lastIndex });
    }
  }
  if (bareCmds.length === 0) return line;

  // 3) Merge math chunks + bare commands into ordered anchors.
  const anchors = [
    ...mathChunks.map((c) => ({ ...c, kind: 'math' })),
    ...bareCmds.map((c) => ({ ...c, kind: 'cmd' })),
  ].sort((a, b) => a.start - b.start);

  // 4) Group consecutive anchors whose "glue" is math-friendly. A
  //    glue chunk fails when it contains a 4+ letter alphabetic word
  //    (treated as prose). We also bail on sentence terminators.
  const isGlueFriendly = (g) => {
    if (g.includes('\n')) return false;
    // Strip math-glue chars then look at what's left.
    const residue = g.replace(/[\s+\-=*/^_,()|{}\[\]0-9.]/g, '');
    if (!residue) return true;
    return !/[a-zA-Z]{4,}/.test(residue);
  };

  const spans = [];
  let cur = { start: anchors[0].start, end: anchors[0].end, hasCmd: anchors[0].kind === 'cmd' };
  for (let i = 1; i < anchors.length; i++) {
    const glue = line.slice(cur.end, anchors[i].start);
    if (isGlueFriendly(glue)) {
      cur.end = anchors[i].end;
      if (anchors[i].kind === 'cmd') cur.hasCmd = true;
    } else {
      spans.push(cur);
      cur = { start: anchors[i].start, end: anchors[i].end, hasCmd: anchors[i].kind === 'cmd' };
    }
  }
  spans.push(cur);

  // Only spans that carried at least one bare `\cmd` need fixing —
  // pure `$..$` spans are already well-formed.
  const fixSpans = spans.filter((s) => s.hasCmd);
  if (fixSpans.length === 0) return line;

  // 5) Extend each fixable span forward through trailing math-glue
  //    (e.g. " dx" or " = 0"). Stops at sentence punctuation or a 4+
  //    letter prose word.
  for (const s of fixSpans) {
    let pos = s.end;
    while (pos < line.length) {
      const ch = line[pos];
      if (ch === '\n') break;
      if (GLUE_CHAR_RE.test(ch)) { pos++; continue; }
      if (/[0-9]/.test(ch)) { pos++; continue; }
      if (/[a-zA-Z]/.test(ch)) {
        const wm = line.slice(pos).match(/^[a-zA-Z]+/);
        if (wm[0].length <= 3) { pos += wm[0].length; continue; }
        break;
      }
      // Sentence punctuation or anything else → stop.
      break;
    }
    while (pos > s.end && /\s/.test(line[pos - 1])) pos--;
    s.end = pos;
  }

  // 6) Apply right-to-left so earlier indices stay valid.
  fixSpans.sort((a, b) => b.start - a.start);
  let result = line;
  for (const s of fixSpans) {
    const inner = result.slice(s.start, s.end);
    const body = inner
      .replace(/\${1,2}/g, '')      // strip nested math markers
      .replace(/\s+/g, ' ')         // collapse whitespace
      .trim();
    if (!body) continue;
    result = result.slice(0, s.start) + '$' + body + '$' + result.slice(s.end);
  }
  return result;
}

function unifyBrokenMath(s) {
  return s.split('\n').map(unifyBrokenMathLine).join('\n');
}

function normalize(text) {
  if (text == null) return '';
  let s = String(text).replace(/\r\n?/g, '\n');

  // Bracket block-math → $$ ... $$. The replacement uses `$$$$` to emit
  // a literal `$$` (each `$$` in a replacement string evaluates to `$`).
  s = s.replace(BRACKET_MATH_RE, (_m, inner) => `$$${inner.trim()}$$`);

  // Parenthesised inline math → $...$. Skipped when preceded by a word
  // character or another `$` to avoid breaking `f(x)` or `$5 (USD)`.
  s = s.replace(PAREN_MATH_RE, (_m, inner) => `$${inner.trim()}$`);

  // `||...||` with LaTeX inside → `$\| ... \|$` (norm). Do this BEFORE
  // the single-bar pass so we don't half-match the inner pair.
  s = s.replace(DOUBLE_PIPE_MATH_RE, (_m, inner) => `$\\|${inner.trim()}\\|$`);

  // `|expr|^n` (or just `|expr|`) with LaTeX inside → `$|expr|^n$`.
  s = s.replace(PIPE_MATH_RE, (_m, inner, sup) => `$|${inner.trim()}|${sup || ''}$`);

  // Final per-line pass — merges fragmented math spans (`\int $$...$$ dy
  // = \int (...) dx`, `$\vec{a}$ \cdot $\vec{b}$`, etc.) into a single
  // `$...$`. Replaces both the older `mergeAdjacentMath` and the
  // bare-command wrapping pass.
  s = unifyBrokenMath(s);

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
