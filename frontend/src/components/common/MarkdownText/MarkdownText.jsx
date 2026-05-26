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
// The LLM emits unreliable `$...$` pairs: it forgets the closing `$`,
// swaps the opening `$` with the closing one, scatters extra `$$$`
// near `$$..$$` blocks, and so on. Treating any `$` as authoritative
// causes worse output than the original (e.g. `\omega$ and $2\omega`
// gets parsed as the literal phrase ` and ` being math).
//
// Strategy: on any line containing a `\command`, we
//   1) protect `$$..$$` block math (those are usually right),
//   2) strip ALL remaining single `$` markers (they're unreliable),
//   3) rebuild math spans purely from `\command` anchors + math-glue
//      (digits, operators, parens, short 1–3 letter identifiers like
//      `dx`/`sin`), stopping at known prose words or 4+ letter words,
//   4) wrap each rebuilt span in `$...$` once,
//   5) restore the block-math regions.
//
// Lines with NO `\command` are left completely alone, so balanced
// `$x^2+y^2=r^2$` stays untouched.
// ---------------------------------------------------------------------------

// Short prose words we stop math-span extension on. 1–3 letter math
// identifiers NOT in this set (e.g. `dx`, `dy`, `dt`, `sin`, `cos`,
// `tan`, `log`, `ln`, `Im`, `Re`) are treated as math.
const PROSE_SHORT_WORDS = new Set([
  'a', 'an', 'as', 'at', 'be', 'by', 'do', 'eg', 'go', 'ie', 'if',
  'in', 'is', 'it', 'no', 'of', 'on', 'or', 'so', 'to', 'up', 'us',
  'we', 'and', 'all', 'any', 'are', 'but', 'can', 'for', 'get',
  'had', 'has', 'how', 'its', 'let', 'may', 'new', 'not', 'now',
  'one', 'our', 'out', 'put', 'see', 'set', 'the', 'two', 'use',
  'was', 'way', 'who', 'why', 'has', 'have', 'were', 'will', 'with',
  'this', 'that', 'than', 'then', 'when', 'where', 'over', 'from',
  'into', 'must', 'find', 'need', 'each', 'just',
]);

const PROSE_WORD_LEN_CUTOFF = 4; // 4+ letter words are prose unless in set
const BARE_CMD_TOKEN_RE = /\\[a-zA-Z]+(?:\{[^{}\n]*\})*/g;
const BLOCK_MATH_RE = /\$\$([^$\n]+?)\$\$/g;

function isMathChar(ch) {
  // Single-character class: operators, digits, brackets, pipes, braces.
  // Whitespace is NOT here — caller handles it separately so we can
  // distinguish whitespace-before-prose vs whitespace-before-math.
  return /[+\-=*/^_,()|{}[\]0-9]/.test(ch);
}

function wordAt(text, i, dir /* 'forward' | 'backward' */) {
  // Returns the letters-only word touching position `i` in the given
  // direction. `forward` = letters starting AT `i`, `backward` = letters
  // ending JUST BEFORE `i`. Returns {word, start, end} or null.
  if (dir === 'forward') {
    const m = text.slice(i).match(/^[a-zA-Z]+/);
    if (!m) return null;
    return { word: m[0], start: i, end: i + m[0].length };
  }
  let end = i;
  let start = i;
  while (start > 0 && /[a-zA-Z]/.test(text[start - 1])) start--;
  if (start === end) return null;
  return { word: text.slice(start, end), start, end };
}

function shouldStopAtWord(word) {
  const lower = word.toLowerCase();
  if (PROSE_SHORT_WORDS.has(lower)) return true;
  if (word.length >= PROSE_WORD_LEN_CUTOFF) return true;
  return false;
}

function extendForward(text, from) {
  let pos = from;
  const n = text.length;
  while (pos < n) {
    const ch = text[pos];
    if (ch === '\n') break;
    if (/\s/.test(ch)) { pos++; continue; }
    if (isMathChar(ch)) { pos++; continue; }
    if (ch === '\\') {
      const m = text.slice(pos).match(/^\\[a-zA-Z]+(?:\{[^{}\n]*\})*/);
      if (m) { pos += m[0].length; continue; }
      break;
    }
    if (/[a-zA-Z]/.test(ch)) {
      const w = wordAt(text, pos, 'forward');
      if (!w) break;
      if (shouldStopAtWord(w.word)) break;
      pos = w.end;
      continue;
    }
    // Sentence punctuation, currency, etc.
    break;
  }
  while (pos > from && /\s/.test(text[pos - 1])) pos--;
  return pos;
}

function extendBackward(text, from) {
  let pos = from;
  while (pos > 0) {
    const before = text[pos - 1];
    if (before === '\n') break;
    if (/\s/.test(before)) { pos--; continue; }
    if (isMathChar(before)) { pos--; continue; }
    if (/[a-zA-Z]/.test(before)) {
      const w = wordAt(text, pos, 'backward');
      if (!w) break;
      if (shouldStopAtWord(w.word)) break;
      pos = w.start;
      continue;
    }
    // Hitting `\` from the wrong direction is rare — bail.
    break;
  }
  while (pos < from && /\s/.test(text[pos])) pos++;
  return pos;
}

function unifyBrokenMathLine(line) {
  // Cheap rejects.
  if (line.length === 0 || line.indexOf('\\') === -1) return line;
  if (/^(\s{4,}|```)/.test(line)) return line;

  // 1) Protect `$$..$$` block math (use Unicode null markers as a
  //    placeholder so the rest of the work can ignore them).
  const blockChunks = [];
  let working = line.replace(BLOCK_MATH_RE, (_m, inner) => {
    const idx = blockChunks.length;
    blockChunks.push(inner.trim());
    return ` BM${idx} `;
  });

  // 2) If the line still has any `\command`, strip ALL remaining `$`
  //    because their positions are unreliable. (If the line had only
  //    well-formed math without any backslash command, we already
  //    bailed at step 0 — that text stays untouched.)
  if (working.indexOf('\\') === -1) {
    // The `\command` was inside the block math we already protected —
    // restore and exit, no further work to do.
    return working.replace(/ BM(\d+) /g, (_m, idx) => `$$${blockChunks[idx]}$$`);
  }
  working = working.replace(/\$/g, '');

  // 3) Find every `\command{args}*` and build a math span around each.
  const cmds = [];
  BARE_CMD_TOKEN_RE.lastIndex = 0;
  let mm;
  while ((mm = BARE_CMD_TOKEN_RE.exec(working)) !== null) {
    cmds.push({ start: mm.index, end: BARE_CMD_TOKEN_RE.lastIndex });
  }
  if (cmds.length === 0) {
    return working.replace(/ BM(\d+) /g, (_m, idx) => `$$${blockChunks[idx]}$$`);
  }

  // Each command grows into a span via left + right extension. Spans
  // that touch / overlap get merged.
  const rawSpans = cmds.map((c) => ({
    start: extendBackward(working, c.start),
    end: extendForward(working, c.end),
  }));

  rawSpans.sort((a, b) => a.start - b.start);
  const spans = [];
  for (const s of rawSpans) {
    if (spans.length && s.start <= spans[spans.length - 1].end) {
      spans[spans.length - 1].end = Math.max(
        spans[spans.length - 1].end,
        s.end,
      );
    } else {
      spans.push({ ...s });
    }
  }

  // 4) Wrap each span in `$...$`, right-to-left so earlier indices stay valid.
  spans.sort((a, b) => b.start - a.start);
  let result = working;
  for (const s of spans) {
    const body = result.slice(s.start, s.end).replace(/\s+/g, ' ').trim();
    if (!body) continue;
    result = result.slice(0, s.start) + '$' + body + '$' + result.slice(s.end);
  }

  // 5) Restore block math.
  return result.replace(
    / BM(\d+) /g,
    (_m, idx) => `$$${blockChunks[idx]}$$`,
  );
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
