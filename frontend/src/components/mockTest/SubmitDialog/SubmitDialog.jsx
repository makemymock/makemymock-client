import { useEffect, useRef } from 'react';
import Button from '../../common/Button/Button';
import styles from './SubmitDialog.module.css';

const SubmitDialog = ({ open, onClose, onConfirm, stats, submitting }) => {
  const dialogRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement;
    dialogRef.current?.focus();
    return () => {
      if (prev && typeof prev.focus === 'function') prev.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e) => {
      if (e.key === 'Escape' && !submitting) onClose?.();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose, submitting]);

  if (!open) return null;

  return (
    <div className={styles.backdrop} role="presentation" onClick={submitting ? undefined : onClose}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-labelledby="submit-dialog-title"
        ref={dialogRef}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="submit-dialog-title" className={styles.title}>Submit this mock test?</h2>
        <p className={styles.subtitle}>
          Once submitted you can't change your answers. Unanswered questions
          will be graded as wrong but won't hurt your topic priority unfairly —
          the recommender treats them as a low-confidence signal.
        </p>

        <dl className={styles.stats}>
          <div className={styles.statItem}>
            <dt>Answered</dt><dd>{stats.answered}</dd>
          </div>
          <div className={styles.statItem}>
            <dt>Marked for review</dt><dd>{stats.marked}</dd>
          </div>
          <div className={styles.statItem}>
            <dt>Not answered</dt><dd>{stats.unanswered}</dd>
          </div>
          <div className={styles.statItem}>
            <dt>Total questions</dt><dd>{stats.total}</dd>
          </div>
        </dl>

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.cancel}
            onClick={onClose}
            disabled={submitting}
          >
            Keep going
          </button>
          <Button
            variant="primary"
            fullWidth={false}
            loading={submitting}
            disabled={submitting}
            onClick={onConfirm}
          >
            Submit test
          </Button>
        </div>
      </div>
    </div>
  );
};

export default SubmitDialog;
