import styles from './BarChart.module.css';

const BarChart = ({
  rows = [],
  valueSuffix = '',
  emptyMessage = 'No data yet.',
  format = (v) => v.toFixed(1),
}) => {
  if (!rows.length) {
    return <p className={styles.empty}>{emptyMessage}</p>;
  }
  const maxV = rows.reduce((m, r) => Math.max(m, Number(r.value) || 0), 1);

  return (
    <ul className={styles.list}>
      {rows.map((r, idx) => {
        const w = Math.min(100, ((Number(r.value) || 0) / maxV) * 100);
        return (
          <li key={r.label || idx}>
            <div className={styles.row}>
              <span className={styles.label}>{r.label}</span>
              {r.meta ? <span className={styles.meta}>{r.meta}</span> : null}
              <span className={styles.value}>
                {format(Number(r.value) || 0)}
                {valueSuffix}
              </span>
            </div>
            <div className={styles.track}>
              <div
                className={styles.fill}
                style={{
                  width: `${w}%`,
                  background: r.color || undefined,
                }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
};

export default BarChart;
