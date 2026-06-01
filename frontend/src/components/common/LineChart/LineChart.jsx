import { useId, useMemo, useRef, useState } from 'react';
import styles from './LineChart.module.css';

const DEFAULT_HEIGHT = 220;
const DEFAULT_WIDTH = 720;
const PADDING = { top: 18, right: 18, bottom: 28, left: 36 };

// X-distance (in SVG units) within which the cursor "snaps" to a data
// point and the tooltip appears. Cursor outside this band shows only
// the crosshair, mirroring GCP / Grafana metric chart behaviour.
const SNAP_THRESHOLD = 22;

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
  const svgRef = useRef(null);
  // Cursor position in SVG coordinates while inside the chart area.
  // Null when the cursor is outside the chart bounds.
  const [cursor, setCursor] = useState(null);
  // Snapped point — set only when the cursor's x is within SNAP_THRESHOLD
  // of a data point's x. Carries the rendered position and the formatted
  // value so the tooltip can read it directly.
  const [snap, setSnap] = useState(null);

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

  // Convert a DOM mouse event to SVG coordinates and update the cursor /
  // snapped-point state. We use createSVGPoint + getScreenCTM rather
  // than offsetX/offsetY so the math works regardless of how the SVG is
  // scaled by `preserveAspectRatio="none"`.
  const handleMove = (e) => {
    const svg = svgRef.current;
    if (!svg) return;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return;
    const local = pt.matrixTransform(ctm.inverse());

    const cx = local.x;
    const cy = local.y;
    const insideChart =
      cx >= PADDING.left
      && cx <= width - PADDING.right
      && cy >= PADDING.top
      && cy <= height - PADDING.bottom;

    if (!insideChart) {
      setCursor(null);
      setSnap(null);
      return;
    }
    setCursor({ x: cx, y: cy });

    // Find the data point whose x is closest to the cursor's x. Across
    // all series — if a chart has multiple series we pick the nearest
    // single dot rather than stacking multiple tooltips.
    let best = null;
    let bestDist = Infinity;
    for (const s of series) {
      for (const p of s.points || []) {
        if (p.x == null || p.y == null) continue;
        const pxX = sx(p.x);
        const dist = Math.abs(pxX - cx);
        if (dist < bestDist) {
          bestDist = dist;
          best = {
            seriesName: s.name || '',
            x: p.x,
            y: Number(p.y),
            cx: pxX,
            cy: sy(p.y),
            color: s.dotColor || s.color || 'var(--color-accent)',
          };
        }
      }
    }
    setSnap(best && bestDist <= SNAP_THRESHOLD ? best : null);
  };

  const handleLeave = () => {
    setCursor(null);
    setSnap(null);
  };

  return (
    <div className={styles.wrap}>
      <svg
        ref={svgRef}
        className={styles.svg}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={ariaLabel}
        preserveAspectRatio="none"
        onMouseMove={handleMove}
        onMouseLeave={handleLeave}
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
            <g key={s.name || sIdx} pointerEvents="none">
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
                />
              ))}
            </g>
          );
        })}

        {/* Crosshair — dotted vertical + horizontal lines that follow the
            cursor whenever it's inside the chart area. Always rendered
            on hover, regardless of whether a data point is nearby. */}
        {cursor ? (
          <g pointerEvents="none">
            <line
              x1={cursor.x}
              x2={cursor.x}
              y1={PADDING.top}
              y2={height - PADDING.bottom}
              className={styles.crosshair}
            />
            <line
              x1={PADDING.left}
              x2={width - PADDING.right}
              y1={cursor.y}
              y2={cursor.y}
              className={styles.crosshair}
            />
          </g>
        ) : null}

        {/* Snap-point highlight — enlarged ring drawn around the nearest
            data point when the cursor's x is within SNAP_THRESHOLD. */}
        {snap ? (
          <g pointerEvents="none">
            <circle
              cx={snap.cx}
              cy={snap.cy}
              r="6"
              fill="none"
              stroke={snap.color}
              strokeWidth="2"
              opacity="0.55"
            />
            <circle
              cx={snap.cx}
              cy={snap.cy}
              r="3.5"
              fill={snap.color}
            />
          </g>
        ) : null}
      </svg>

      {/* HTML tooltip — only when the cursor is snapped to a data point.
          Position via percentages so it tracks the SVG through resizes
          (the SVG uses preserveAspectRatio="none"). */}
      {snap ? (
        <div
          className={styles.tooltip}
          style={{
            left: `${(snap.cx / width) * 100}%`,
            top: `${(snap.cy / height) * 100}%`,
          }}
        >
          {snap.seriesName ? (
            <span className={styles.tooltipTitle}>{snap.seriesName}</span>
          ) : null}
          <span className={styles.tooltipMeta}>{formatDate(snap.x)}</span>
          <span className={styles.tooltipValue}>{yTickFormat(snap.y)}</span>
        </div>
      ) : null}

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
