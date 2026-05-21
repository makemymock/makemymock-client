import MarkdownText from '../../common/MarkdownText/MarkdownText';
import styles from './MatchingEditor.module.css';

// Renders a left column of items and lets the user pick one right-column
// item per left row via a select. Read-only mode shades correctness.
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
                    <select
                      className={styles.select}
                      value={chosen}
                      onChange={(e) => handleChange(row.key, e.target.value)}
                      aria-label={`Match for ${row.key}`}
                    >
                      <option value="">— pick —</option>
                      {right.map((opt) => (
                        <option key={opt.key} value={opt.key}>
                          {opt.key} · {opt.text}
                        </option>
                      ))}
                    </select>
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

export default MatchingEditor;
