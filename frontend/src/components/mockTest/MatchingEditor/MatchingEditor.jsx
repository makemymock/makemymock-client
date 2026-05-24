import { useEffect, useRef, useState } from 'react';
import MarkdownText from '../../common/MarkdownText/MarkdownText';
import styles from './MatchingEditor.module.css';

// Renders a left column of items and lets the user pick one right-column
// item per left row. Read-only mode shades correctness.
//
// The dropdown is a custom popover (NOT a native <select>) because native
// <option> elements only render plain text — they strip HTML and can't
// run KaTeX. We need each option to display rendered LaTeX, so we built
// our own.
const MatchingEditor = ({ left, right, value, onChange, readOnly = false, correctMapping = null }) => {
  const handleChange = (leftKey, rightKey) => {
    const next = { ...(value || {}) };
    if (rightKey === '') {
      delete next[leftKey];
    } else {
      next[leftKey] = rightKey;
    }
    onChange?.(next);
  };

  return (
    <div className={styles.wrapper} role="group" aria-label="Matching question">
      <table className={styles.table}>
        <thead>
          <tr>
            <th className={styles.colHead}>Item</th>
            <th className={styles.colHead}>Match</th>
          </tr>
        </thead>
        <tbody>
          {left.map((row) => {
            const chosen = (value || {})[row.key] || '';
            let rowClass = '';
            if (readOnly && correctMapping) {
              const expected = correctMapping[row.key];
              if (chosen && expected) {
                rowClass = chosen === expected ? styles.rowCorrect : styles.rowWrong;
              } else if (!chosen) {
                rowClass = styles.rowWrong;
              }
            }
            return (
              <tr key={row.key} className={rowClass}>
                <td className={styles.cell}>
                  <span className={styles.itemKey}>{row.key}</span>
                  <span className={styles.itemText}>
                    <MarkdownText text={row.text} inline />
                  </span>
                </td>
                <td className={styles.cell}>
                  {readOnly ? (
                    <span className={styles.readOnlyVal}>
                      {chosen || <em className={styles.emptyVal}>not answered</em>}
                      {correctMapping && correctMapping[row.key] && correctMapping[row.key] !== chosen ? (
                        <span className={styles.expected}>
                          (correct: <strong>{correctMapping[row.key]}</strong>)
                        </span>
                      ) : null}
                    </span>
                  ) : (
                    <LatexSelect
                      options={right}
                      value={chosen}
                      onChange={(rightKey) => handleChange(row.key, rightKey)}
                      ariaLabel={`Match for ${row.key}`}
                    />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <details className={styles.refColumn}>
        <summary>Reference column</summary>
        <ul>
          {right.map((opt) => (
            <li key={opt.key}>
              <strong>{opt.key}.</strong> <MarkdownText text={opt.text} inline />
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
};

// ---------------------------------------------------------------------------
// LatexSelect — a click-to-open dropdown whose options render LaTeX/markdown.
// ---------------------------------------------------------------------------

const LatexSelect = ({ options, value, onChange, ariaLabel }) => {
  const [open, setOpen] = useState(false);
  const rootRef = useRef(null);
  const selected = options.find((o) => o.key === value) || null;

  // Close on outside click + Escape key.
  useEffect(() => {
    if (!open) return undefined;
    const onDocClick = (e) => {
      if (rootRef.current && !rootRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const pick = (key) => {
    onChange(key);
    setOpen(false);
  };

  return (
    <div className={styles.lselect} ref={rootRef}>
      <button
        type="button"
        className={`${styles.lselectTrigger} ${open ? styles.lselectTriggerOpen : ''}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
      >
        <span className={styles.lselectValue}>
          {selected ? (
            <>
              <span className={styles.lselectValueKey}>{selected.key}</span>
              <span className={styles.lselectValueText}>
                <MarkdownText text={selected.text} inline />
              </span>
            </>
          ) : (
            <span className={styles.lselectPlaceholder}>— pick —</span>
          )}
        </span>
        <span aria-hidden="true" className={styles.lselectChevron}>▾</span>
      </button>

      {open ? (
        <ul className={styles.lselectMenu} role="listbox" aria-label={ariaLabel}>
          <li className={styles.lselectClear}>
            <button
              type="button"
              className={styles.lselectClearBtn}
              onClick={() => pick('')}
            >
              — pick —
            </button>
          </li>
          {options.map((opt) => {
            const isActive = opt.key === value;
            return (
              <li key={opt.key} role="option" aria-selected={isActive}>
                <button
                  type="button"
                  className={`${styles.lselectItem} ${
                    isActive ? styles.lselectItemActive : ''
                  }`}
                  onClick={() => pick(opt.key)}
                >
                  <span className={styles.lselectItemKey}>{opt.key}</span>
                  <span className={styles.lselectItemText}>
                    <MarkdownText text={opt.text} inline />
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
};

export default MatchingEditor;
