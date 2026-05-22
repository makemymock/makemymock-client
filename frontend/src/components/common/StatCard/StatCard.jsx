import styles from './StatCard.module.css';

const StatCard = ({ label, value, sub, tone }) => (
  <div className={`${styles.card} ${tone ? styles[tone] : ''}`}>
    <span className={styles.label}>{label}</span>
    <span className={styles.value}>{value}</span>
    {sub ? <span className={styles.sub}>{sub}</span> : null}
  </div>
);

export default StatCard;
