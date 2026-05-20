import { useState } from 'react';
import styles from './QaCard.module.css';

export default function QaCard({ card, pinPosition = 'center', style, variant = 'floating', className = '' }) {
  const [isOpen, setIsOpen] = useState(false);

  const baseClass = variant === 'fill' ? styles.wrapperFill : styles.wrapper;
  const wrapperClass = `${baseClass} ${className}`.trim();
  const cardClass = `${styles.card}${isOpen ? ` ${styles.cardOpen}` : ''}`;

  return (
    <div className={wrapperClass} data-pin={pinPosition} style={style}>
      <div className={styles.pin} aria-hidden="true">📌</div>
      <article
        className={cardClass}
        onMouseEnter={() => setIsOpen(true)}
        onMouseLeave={() => setIsOpen(false)}
        onFocus={() => setIsOpen(true)}
        onBlur={() => setIsOpen(false)}
        tabIndex={0}
        aria-expanded={isOpen}
      >
        <h3>{card.title}</h3>
        <div className={styles.answer}>
          <p>{card.fullText}</p>
        </div>
        {!isOpen && (
          <span className={styles.toggle} aria-hidden="true">read here</span>
        )}
      </article>
    </div>
  );
}
