import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import MarkdownText from '../../common/MarkdownText/MarkdownText';
import styles from './MatchingEditor.module.css';

// Matrix-match editor.
//
// Layout:
//   1. Reference panel — Column I (P1..Pn) and Column II (Q1..Qm) side-by-side
//      with curved SVG lines drawn from each picked P to its matched Q(s).
//      Lines update live as the student ticks cells in the matrix below.
//   2. Answer matrix — compact n×m checkbox grid where ticks are entered.
//   3. Read-only review: lines are colored green (hit), red (wrong), or
//      dashed-green (correct answer missed); the matrix cells are similarly
//      shaded; correct answer is also listed in text form below.
//
// Answer shape (wire & local): `{ "<row_idx>": ["<col_idx>", ...] }`.

function rowColor(i, total) {
  // Evenly-spaced HSL hue per row — works for any n.
  const hue = (i * 360) / Math.max(total, 1);
  return `hsl(${hue}, 70%, 58%)`;
}

const MatchingEditor = ({
  left,
  right,
  value,
  onChange,
  readOnly = false,
  correctMapping = null,
}) => {
  const n = left?.length || 0;
  const m = right?.length || 0;
  const picked = useMemo(() => toRowSetMap(value), [value]);
  const expected = useMemo(() => toRowSetMap(correctMapping), [correctMapping]);

  const toggle = (rowIdx, colIdx) => {
    if (readOnly) return;
    const key = String(rowIdx);
    const col = String(colIdx);
    const current = new Set(picked.get(key) || []);
    if (current.has(col)) current.delete(col);
    else current.add(col);

    const next = {};
    for (const [k, set] of picked.entries()) {
      if (k === key) continue;
      if (set.size > 0) next[k] = Array.from(set).sort(byNumeric);
    }
    if (current.size > 0) next[key] = Array.from(current).sort(byNumeric);
    onChange?.(next);
  };

  return (
    <div className={styles.wrapper} role="group" aria-label="Matrix-match question">
      <ReferencePanel
        left={left}
        right={right}
        picked={picked}
        expected={expected}
        readOnly={readOnly}
      />
      <AnswerMatrix
        n={n}
        m={m}
        picked={picked}
        expected={expected}
        readOnly={readOnly}
        onToggle={toggle}
      />
      {readOnly ? (
        <CorrectAnswerText n={n} expected={expected} />
      ) : null}
    </div>
  );
};

// --------------------------------------------------------------------------
// Reference panel + SVG lines
// --------------------------------------------------------------------------

function ReferencePanel({ left, right, picked, expected, readOnly }) {
  const containerRef = useRef(null);
  const leftRefs = useRef([]);
  const rightRefs = useRef([]);
  const [paths, setPaths] = useState([]);
  const n = left?.length || 0;

  useLayoutEffect(() => {
    const compute = () => {
      const c = containerRef.current;
      if (!c) return;
      const cRect = c.getBoundingClientRect();

      const endPoint = (rect, side) => ({
        x: (side === 'right' ? rect.right : rect.left) - cRect.left,
        y: rect.top + rect.height / 2 - cRect.top,
      });

      const out = [];

      for (const [rowKey, colSet] of picked.entries()) {
        const i = Number(rowKey);
        const lEl = leftRefs.current[i];
        if (!lEl) continue;
        const a = endPoint(lEl.getBoundingClientRect(), 'right');
        for (const col of colSet) {
          const j = Number(col);
          const rEl = rightRefs.current[j];
          if (!rEl) continue;
          const b = endPoint(rEl.getBoundingClientRect(), 'left');
          let kind = 'pick';
          if (readOnly) {
            const isCorrect = !!expected.get(rowKey)?.has(col);
            kind = isCorrect ? 'hit' : 'wrong';
          }
          out.push({ a, b, row: i, kind });
        }
      }

      if (readOnly) {
        for (const [rowKey, colSet] of expected.entries()) {
          const i = Number(rowKey);
          const lEl = leftRefs.current[i];
          if (!lEl) continue;
          const a = endPoint(lEl.getBoundingClientRect(), 'right');
          for (const col of colSet) {
            if (picked.get(rowKey)?.has(col)) continue;
            const j = Number(col);
            const rEl = rightRefs.current[j];
            if (!rEl) continue;
            const b = endPoint(rEl.getBoundingClientRect(), 'left');
            out.push({ a, b, row: i, kind: 'missed' });
          }
        }
      }

      setPaths(out);
    };

    compute();
    const ro = new ResizeObserver(compute);
    if (containerRef.current) ro.observe(containerRef.current);
    [...leftRefs.current, ...rightRefs.current].forEach((el) => el && ro.observe(el));
    return () => ro.disconnect();
  }, [picked, expected, left, right, readOnly]);

  return (
    <div ref={containerRef} className={styles.refPanel}>
      <section className={styles.refCol}>
        <h4 className={styles.refColHead}>Column I</h4>
        <ol className={styles.refList}>
          {left.map((t, i) => (
            <li
              key={`p-${i}`}
              ref={(el) => (leftRefs.current[i] = el)}
              className={styles.refItem}
            >
              <span
                className={styles.refLabel}
                style={{ color: rowColor(i, n) }}
              >
                P{i + 1}.
              </span>
              <span className={styles.refText}>
                <MarkdownText text={t} inline />
              </span>
            </li>
          ))}
        </ol>
      </section>

      <section className={styles.refCol}>
        <h4 className={styles.refColHead}>Column II</h4>
        <ol className={styles.refList}>
          {right.map((t, j) => (
            <li
              key={`q-${j}`}
              ref={(el) => (rightRefs.current[j] = el)}
              className={styles.refItem}
            >
              <span className={styles.refLabel}>Q{j + 1}.</span>
              <span className={styles.refText}>
                <MarkdownText text={t} inline />
              </span>
            </li>
          ))}
        </ol>
      </section>

      <svg className={styles.lineSvg} aria-hidden="true">
        {paths.map((p, idx) => {
          const dx = (p.b.x - p.a.x) * 0.45;
          const d = `M ${p.a.x},${p.a.y} C ${p.a.x + dx},${p.a.y} ${p.b.x - dx},${p.b.y} ${p.b.x},${p.b.y}`;
          let stroke = rowColor(p.row, n);
          let strokeDasharray;
          let opacity = 0.9;
          if (p.kind === 'hit') stroke = '#22c55e';
          else if (p.kind === 'wrong') stroke = '#ef4444';
          else if (p.kind === 'missed') {
            stroke = '#22c55e';
            strokeDasharray = '6 5';
            opacity = 0.75;
          }
          return (
            <path
              key={`line-${idx}`}
              d={d}
              stroke={stroke}
              strokeWidth={2.5}
              strokeDasharray={strokeDasharray}
              strokeLinecap="round"
              fill="none"
              opacity={opacity}
            />
          );
        })}
      </svg>
    </div>
  );
}

// --------------------------------------------------------------------------
// Answer matrix
// --------------------------------------------------------------------------

function AnswerMatrix({ n, m, picked, expected, readOnly, onToggle }) {
  return (
    <div className={styles.matrixBlock}>
      <h4 className={styles.matrixHead}>
        {readOnly ? 'Your matrix' : 'Mark your matches'}
      </h4>
      <div className={styles.matrixScroll}>
        <table className={styles.matrix}>
          <thead>
            <tr>
              <th className={styles.cornerCell} aria-hidden="true" />
              {Array.from({ length: m }, (_, j) => (
                <th key={`mc-${j}`} scope="col" className={styles.matrixColHead}>
                  Q{j + 1}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {Array.from({ length: n }, (_, i) => {
              const rowKey = String(i);
              const rowPicked = picked.get(rowKey) || new Set();
              const rowExpected = expected.get(rowKey) || new Set();
              return (
                <tr key={`mr-${i}`}>
                  <th
                    scope="row"
                    className={styles.matrixRowHead}
                    style={{ color: rowColor(i, n) }}
                  >
                    P{i + 1}
                  </th>
                  {Array.from({ length: m }, (_, j) => {
                    const col = String(j);
                    const isPicked = rowPicked.has(col);
                    const isExpected = rowExpected.has(col);
                    return (
                      <td key={`mcell-${i}-${j}`} className={styles.cell}>
                        <button
                          type="button"
                          role="checkbox"
                          aria-checked={isPicked}
                          aria-label={`P${i + 1} matches Q${j + 1}`}
                          className={cellClass({ readOnly, isPicked, isExpected })}
                          onClick={() => onToggle(i, j)}
                          disabled={readOnly}
                        >
                          <span aria-hidden="true">
                            {readOnly
                              ? cellGlyph({ isPicked, isExpected })
                              : (isPicked ? '●' : '')}
                          </span>
                        </button>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// Read-only: correct-answer text block
// --------------------------------------------------------------------------

function CorrectAnswerText({ n, expected }) {
  const rows = [];
  for (let i = 0; i < n; i++) {
    const set = expected.get(String(i));
    if (set && set.size > 0) {
      const cols = Array.from(set).map((c) => Number(c)).sort((a, b) => a - b);
      rows.push({ row: i, cols });
    }
  }
  if (rows.length === 0) return null;
  return (
    <div className={styles.correctBlock}>
      <h4 className={styles.correctHead}>Correct answer</h4>
      <ul className={styles.correctList}>
        {rows.map(({ row, cols }) => (
          <li key={`er-${row}`}>
            <span
              className={styles.correctLabel}
              style={{ color: rowColor(row, n) }}
            >
              P{row + 1}
            </span>
            <span className={styles.correctArrow}>↔</span>
            <span className={styles.correctCols}>
              {cols.map((c) => `Q${c + 1}`).join(', ')}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// --------------------------------------------------------------------------
// helpers
// --------------------------------------------------------------------------

function toRowSetMap(raw) {
  const out = new Map();
  if (!raw || typeof raw !== 'object') return out;
  for (const [k, v] of Object.entries(raw)) {
    const key = String(k);
    if (v == null) {
      out.set(key, new Set());
    } else if (Array.isArray(v)) {
      out.set(key, new Set(v.map((x) => String(x))));
    } else {
      out.set(key, new Set([String(v)]));
    }
  }
  return out;
}

function byNumeric(a, b) {
  const na = Number(a);
  const nb = Number(b);
  if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb;
  return String(a).localeCompare(String(b));
}

function cellClass({ readOnly, isPicked, isExpected }) {
  const parts = [styles.cellBtn];
  if (!readOnly) {
    if (isPicked) parts.push(styles.cellPicked);
  } else {
    if (isPicked && isExpected) parts.push(styles.cellHit);
    else if (isPicked && !isExpected) parts.push(styles.cellWrong);
    else if (!isPicked && isExpected) parts.push(styles.cellMissed);
  }
  return parts.join(' ');
}

function cellGlyph({ isPicked, isExpected }) {
  if (isPicked && isExpected) return '✓';
  if (isPicked && !isExpected) return '✗';
  if (!isPicked && isExpected) return '·';
  return '';
}

export default MatchingEditor;
