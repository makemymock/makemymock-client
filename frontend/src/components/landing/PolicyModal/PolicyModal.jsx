import { useEffect } from 'react';
import MarkdownText from '../../common/MarkdownText/MarkdownText';
import styles from './PolicyModal.module.css';

// Lightweight popup that renders a legal policy (Privacy / Terms / Refund /
// Cookie) from its markdown source. The policy text lives in
// `src/content/legal/*.md` and is passed in as `body`; we just present it.
// Closes on backdrop click, the × button, or Escape, and locks page scroll
// while open.
const PolicyModal = ({ title, body, onClose }) => {
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  return (
    <div
      className={styles.backdrop}
      role="dialog"
      aria-modal="true"
      aria-labelledby="policyModalTitle"
      onClick={onClose}
    >
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <header className={styles.head}>
          <h2 id="policyModalTitle" className={styles.title}>{title}</h2>
          <button
            type="button"
            className={styles.close}
            onClick={onClose}
            aria-label="Close"
          >
            ×
          </button>
        </header>
        <div className={styles.body}>
          <MarkdownText text={body} className={styles.markdown} />
        </div>
      </div>
    </div>
  );
};

export default PolicyModal;
