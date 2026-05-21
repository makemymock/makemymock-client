import styles from './QuestionPalette.module.css';

// Each item: { question_id, display_order, status: 'unanswered'|'answered'|'marked'|'answered_marked', isActive }
const QuestionPalette = ({ items, onJump, legend = true }) => {
  return (
    <aside className={styles.wrapper} aria-label="Question palette">
      <header className={styles.head}>
        <h3 className={styles.title}>Questions</h3>
        <span className={styles.count}>{items.length}</span>
      </header>

      <ol className={styles.grid}>
        {items.map((item, idx) => {
          const cls = [
            styles.tile,
            styles[item.status] || '',
            item.isActive ? styles.active : '',
          ].filter(Boolean).join(' ');
          return (
            <li key={item.question_id}>
              <button
                type="button"
                className={cls}
                onClick={() => onJump?.(idx)}
                aria-label={`Question ${idx + 1} ${item.status.replace('_', ' ')}`}
                aria-current={item.isActive ? 'true' : undefined}
              >
                {idx + 1}
              </button>
            </li>
          );
        })}
      </ol>

      {legend && (
        <ul className={styles.legend}>
          <li><span className={`${styles.swatch} ${styles.unanswered}`} /> Not answered</li>
          <li><span className={`${styles.swatch} ${styles.answered}`} /> Answered</li>
          <li><span className={`${styles.swatch} ${styles.marked}`} /> Marked</li>
          <li><span className={`${styles.swatch} ${styles.answered_marked}`} /> Answered + marked</li>
        </ul>
      )}
    </aside>
  );
};

export default QuestionPalette;
