import { useId, useMemo } from 'react';
import styles from './LineChart.module.css';

const DEFAULT_HEIGHT = 220;
const DEFAULT_WIDTH = 720;
const PADDING = { top: 18, right: 18, bottom: 28, left: 36 };

const formatDate = (d) => {
  if (!d) return '';
  const dt = d instanceof Date ? d : new Date(d);
  return dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
};

const LineChart = ({
  series = [],
  height = DEFAULT_HEIGHT,
  width = DEFAULT_WIDTH,
  yLabel,
  yMin,
  yMax,
  yTickFormat = (v) => v.toFixed(0),
  emptyMessage = 'Not enough data yet.',
  ariaLabel = 'Trend chart',
}) => {
  const gradId = useId();
  const flat = useMemo(
    () => series.flatMap((s) => (s.points || []).map((p) => ({ ...p, _sName: s.name }))),
    [series],
  );

  if (!flat.length) {
    return <p className={styles.empty}>{emptyMessage}</p>;
  }

  const xs = flat.map((p) => +new Date(p.x));
  const ys = flat.map((p) => Number(p.y));
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const calcedYMin = yMin ?? Math.min(...ys, 0);
  const calcedYMax = yMax ?? Math.max(...ys, 1);
  const ySpan = (calcedYMax - calcedYMin) || 1;
  const xSpan = (xMax - xMin) || 1;

  const innerW = width - PADDING.left - PADDING.right;
  const innerH = height - PADDING.top - PADDING.bottom;

  const sx = (x) => PADDING.left + ((+new Date(x) - xMin) / xSpan) * innerW;
  const sy = (y) => PADDING.top + (1 - (Number(y) - calcedYMin) / ySpan) * innerH;

  const tickCount = 4;
  const yTicks = Array.from({ length: tickCount + 1 }, (_, i) => {
    const v = calcedYMin + (ySpan * i) / tickCount;
    return { v, y: sy(v) };
  });

  return (
    <div className={styles.wrap}>
      <svg
        className={styles.svg}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel}
        preserveAspectRatio="none"
      >
        <defs>
          <linearGradient id={`${gradId}-line`} x1="0" x2="1">
            <stop offset="0" stopColor="var(--color-brand-grad-from)" />
            <stop offset="1" stopColor="var(--color-brand-grad-to)" />
          </linearGradient>
        </defs>

        {/* Y grid lines + labels */}
        {yTicks.map((t, i) => (
          <g key={i}>
            <line
              x1={PADDING.left}
              x2={width - PADDING.right}
              y1={t.y}
              y2={t.y}
              className={styles.gridLine}
            />
            <text
              x={PADDING.left - 6}
              y={t.y + 4}
              className={styles.tickLabel}
              textAnchor="end"
            >
              {yTickFormat(t.v)}
            </text>
          </g>
        ))}

        {yLabel ? (
          <text
            transform={`translate(10 ${PADDING.top + innerH / 2}) rotate(-90)`}
            className={styles.axisLabel}
            textAnchor="middle"
          >
            {yLabel}
          </text>
        ) : null}

        {/* X end labels (start, end) */}
        <text
          x={PADDING.left}
          y={height - 8}
          className={styles.tickLabel}
        >
          {formatDate(xMin)}
        </text>
        <text
          x={width - PADDING.right}
          y={height - 8}
          className={styles.tickLabel}
          textAnchor="end"
        >
          {formatDate(xMax)}
        </text>

        {/* Series */}
        {series.map((s, sIdx) => {
          const pts = (s.points || []).filter((p) => p.x != null && p.y != null);
          if (!pts.length) return null;
          const sorted = [...pts].sort((a, b) => +new Date(a.x) - +new Date(b.x));
          const d = sorted
            .map((p, i) => {
              const x = sx(p.x).toFixed(1);
              const y = sy(p.y).toFixed(1);
              return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
            })
            .join(' ');
          const stroke = s.color || `url(#${gradId}-line)`;
          return (
            <g key={s.name || sIdx}>
              <path
                d={d}
                fill="none"
                stroke={stroke}
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
                opacity={s.opacity ?? 1}
              />
              {sorted.map((p, i) => (
                <circle
                  key={i}
                  cx={sx(p.x)}
                  cy={sy(p.y)}
                  r="3"
                  fill={s.dotColor || 'var(--color-accent)'}
                >
                  <title>
                    {`${s.name || ''}${s.name ? ' · ' : ''}${formatDate(p.x)} · ${yTickFormat(Number(p.y))}`}
                  </title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>

      {series.length > 1 ? (
        <ul className={styles.legend}>
          {series.map((s, i) => (
            <li key={s.name || i}>
              <span
                className={styles.legendSwatch}
                style={{ background: s.color || 'var(--color-accent)' }}
              />
              {s.name || `Series ${i + 1}`}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
};

export default LineChart;
