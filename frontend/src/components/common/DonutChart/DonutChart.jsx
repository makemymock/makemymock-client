import styles from './DonutChart.module.css';

const PALETTE = [
  '#14b8a6',
  '#f59e0b',
  '#ef4444',
  '#6366f1',
  '#0ea5e9',
  '#a855f7',
  '#22c55e',
];

function buildArcs(filtered, total, circ) {
  let offset = 0;
  const out = [];
  for (let i = 0; i < filtered.length; i += 1) {
    const s = filtered[i];
    const frac = (Number(s.value) || 0) / total;
    const length = circ * frac;
    out.push({
      ...s,
      color: s.color || PALETTE[i % PALETTE.length],
      dashArray: `${length} ${circ - length}`,
      dashOffset: -offset,
      pct: frac * 100,
    });
    offset += length;
  }
  return out;
}

const DonutChart = ({
  segments = [],
  size = 168,
  thickness = 22,
  centerLabel,
  centerSub,
  emptyMessage = 'No data yet.',
}) => {
  const filtered = (segments || []).filter((s) => (Number(s.value) || 0) > 0);
  if (!filtered.length) {
    return <p className={styles.empty}>{emptyMessage}</p>;
  }

  const total = filtered.reduce((sum, s) => sum + (Number(s.value) || 0), 0);
  const cx = size / 2;
  const cy = size / 2;
  const radius = (size - thickness) / 2;
  const circ = 2 * Math.PI * radius;
  const arcs = buildArcs(filtered, total, circ);

  return (
    <div className={styles.wrap}>
      <svg
        className={styles.svg}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label="Distribution chart"
      >
        <circle
          cx={cx}
          cy={cy}
          r={radius}
          className={styles.track}
          strokeWidth={thickness}
          fill="none"
        />
        {arcs.map((a, i) => (
          <circle
            key={i}
            cx={cx}
            cy={cy}
            r={radius}
            stroke={a.color}
            strokeWidth={thickness}
            fill="none"
            strokeDasharray={a.dashArray}
            strokeDashoffset={a.dashOffset}
            transform={`rotate(-90 ${cx} ${cy})`}
            strokeLinecap="butt"
          >
            <title>{`${a.label}: ${a.value} (${a.pct.toFixed(0)}%)`}</title>
          </circle>
        ))}
        {centerLabel ? (
          <g>
            <text
              x={cx}
              y={cy - 2}
              textAnchor="middle"
              className={styles.centerValue}
            >
              {centerLabel}
            </text>
            {centerSub ? (
              <text
                x={cx}
                y={cy + 16}
                textAnchor="middle"
                className={styles.centerSub}
              >
                {centerSub}
              </text>
            ) : null}
          </g>
        ) : null}
      </svg>

      <ul className={styles.legend}>
        {arcs.map((a, i) => (
          <li key={i}>
            <span className={styles.swatch} style={{ background: a.color }} />
            <span className={styles.legendLabel}>{a.label}</span>
            <span className={styles.legendValue}>
              {a.value} · {a.pct.toFixed(0)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default DonutChart;
