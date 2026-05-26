import { useMemo, useState } from 'react';
import styles from './Heatmap.module.css';

// Range options. `week` is one row of 7 daily cells; `month` is the
// canonical 4×7 grid of the last 28 days; `six_months` rolls the daily
// counts up into ~28 weekly buckets so the 4×7 grid stays visually
// consistent across views (each cell = 1 week instead of 1 day).
const RANGES = [
  { key: 'week',       label: 'Week',     cells: 7,  bucketDays: 1 },
  { key: 'month',      label: 'Month',    cells: 28, bucketDays: 1 },
  { key: 'six_months', label: '6 months', cells: 28, bucketDays: 7 },
];

const DAY_LABELS = ['S', 'M', 'T', 'W', 'T', 'F', 'S'];

const MS_PER_DAY = 24 * 60 * 60 * 1000;

// Parse "YYYY-MM-DD" → Date anchored at LOCAL midnight on the given
// calendar day. The backend keys these by IST date, so an IST browser
// renders this Date at IST midnight and `toLocaleDateString()` shows
// the correct day. Avoids the timezone drift that
// `new Date("YYYY-MM-DD")` causes by parsing the key as UTC.
const parseDay = (key) => {
  const [y, m, d] = key.split('-').map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
};

// Format a local-time Date back to "YYYY-MM-DD" without going through
// toISOString (which would convert to UTC and shift the day for IST).
const formatDayKey = (d) => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const formatDate = (d) =>
  d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });

const formatRangeLabel = (startDate, endDate, bucketDays) => {
  if (bucketDays === 1) {
    return `${formatDate(startDate)} – ${formatDate(endDate)}`;
  }
  // Weekly buckets — show the week's start day.
  return `Week of ${formatDate(startDate)}`;
};

// Map a count → intensity bucket 0–4. Uses a relative scale anchored to
// the max count in the *visible* slice so the brightest cell on the
// week view doesn't look identical to the brightest cell on the six-
// month view when the absolute volumes are very different.
const intensityLevel = (count, sliceMax) => {
  if (count <= 0) return 0;
  if (sliceMax <= 0) return 0;
  const ratio = count / sliceMax;
  if (ratio <= 0.25) return 1;
  if (ratio <= 0.5) return 2;
  if (ratio <= 0.75) return 3;
  return 4;
};

/**
 * Activity heatmap — 4×7 (or 1×7) grid coloured by problem-solving
 * intensity. Renders three views via the range toggle (week / month /
 * 6 months). All buckets are computed from the same `days` payload so
 * switching views doesn't re-fetch.
 *
 * Props:
 *   days       — array of {date: "YYYY-MM-DD", count: number}, oldest → newest,
 *                covering at least the largest range (~182 days).
 *   maxCount   — max single-day count across the payload (advisory; the
 *                visible scale uses the slice max).
 *   className  — optional extra class for the wrapper.
 *   compact    — when true, drops the title row and shrinks padding.
 *                Used by the Dashboard card; the Analytics card uses the
 *                full layout.
 *   defaultRange — initial range key. Defaults to "month".
 */
const Heatmap = ({
  days = [],
  maxCount = 0,        // eslint-disable-line no-unused-vars
  className = '',
  compact = false,
  defaultRange = 'month',
}) => {
  const [rangeKey, setRangeKey] = useState(defaultRange);
  const range = RANGES.find((r) => r.key === rangeKey) || RANGES[1];

  // ---- Build the cells for the currently-selected range. ----
  const { cells, rangeStart, rangeEnd, sliceTotal, sliceMax } = useMemo(() => {
    if (!days || days.length === 0) {
      return { cells: [], rangeStart: null, rangeEnd: null, sliceTotal: 0, sliceMax: 0 };
    }

    // Last `cells * bucketDays` days of the series.
    const neededDays = range.cells * range.bucketDays;
    const recent = days.slice(-neededDays);
    // Pad on the front with zero-buckets if the payload was shorter
    // than the requested window (new user, recently signed up).
    const pad = neededDays - recent.length;
    const padded = pad > 0
      ? Array.from({ length: pad }, (_, i) => {
          // Anchor padded dates against the first real entry.
          const firstReal = recent[0];
          const firstDate = firstReal
            ? parseDay(firstReal.date)
            : new Date();
          const d = new Date(firstDate.getTime() - (pad - i) * MS_PER_DAY);
          return { date: formatDayKey(d), count: 0 };
        }).concat(recent)
      : recent;

    // Bucket into the grid cells.
    const out = [];
    let runningMax = 0;
    let runningTotal = 0;
    for (let i = 0; i < range.cells; i += 1) {
      const slice = padded.slice(i * range.bucketDays, (i + 1) * range.bucketDays);
      const count = slice.reduce((s, d) => s + (Number(d.count) || 0), 0);
      const startKey = slice[0]?.date;
      const endKey = slice[slice.length - 1]?.date;
      const startDate = startKey ? parseDay(startKey) : null;
      const endDate = endKey ? parseDay(endKey) : null;
      out.push({
        index: i,
        startDate,
        endDate,
        count,
        bucketDays: range.bucketDays,
      });
      if (count > runningMax) runningMax = count;
      runningTotal += count;
    }
    return {
      cells: out,
      rangeStart: out[0]?.startDate || null,
      rangeEnd: out[out.length - 1]?.endDate || null,
      sliceTotal: runningTotal,
      sliceMax: runningMax,
    };
  }, [days, range]);

  // ---- Layout dimensions (rows × cols). Week view is 1×7, the others 4×7.
  const cols = 7;
  const rows = Math.ceil(range.cells / cols);

  const empty = !days || days.length === 0;

  return (
    <section className={`${styles.wrap} ${compact ? styles.compact : ''} ${className}`}>
      {!compact ? (
        <header className={styles.head}>
          <div className={styles.headText}>
            <h3 className={styles.title}>Activity heatmap</h3>
            <p className={styles.subtitle}>
              How many problems you've solved each day. Bright green = more,
              dim = quiet.
            </p>
          </div>
        </header>
      ) : null}

      <div className={styles.toolbar}>
        <div
          className={styles.rangeTabs}
          role="tablist"
          aria-label="Heatmap time range"
        >
          {RANGES.map((r) => (
            <button
              key={r.key}
              type="button"
              role="tab"
              aria-selected={rangeKey === r.key}
              className={`${styles.rangeTab} ${
                rangeKey === r.key ? styles.rangeTabActive : ''
              }`}
              onClick={() => setRangeKey(r.key)}
            >
              {r.label}
            </button>
          ))}
        </div>

        <p className={styles.headStat}>
          <strong>{sliceTotal}</strong>
          <span> problems · {range.label.toLowerCase()}</span>
        </p>
      </div>

      {empty ? (
        <p className={styles.empty}>
          No activity yet — solve a mock test to light up your heatmap.
        </p>
      ) : (
        <>
          {/* Column labels — meaningful only when each cell is a single day. */}
          {range.bucketDays === 1 ? (
            <div className={styles.colLabels} aria-hidden="true">
              {DAY_LABELS.map((d, i) => (
                <span key={i} className={styles.colLabel}>{d}</span>
              ))}
            </div>
          ) : null}

          <div
            className={styles.grid}
            style={{ gridTemplateRows: `repeat(${rows}, 1fr)` }}
            role="img"
            aria-label={`Activity heatmap, ${range.label} view, ${sliceTotal} problems solved`}
          >
            {cells.map((cell) => {
              const level = intensityLevel(cell.count, sliceMax);
              const tip = cell.startDate
                ? `${formatRangeLabel(cell.startDate, cell.endDate, cell.bucketDays)}: ${cell.count} problem${cell.count === 1 ? '' : 's'}`
                : '';
              return (
                <span
                  key={cell.index}
                  className={`${styles.cell} ${styles[`lvl${level}`]}`}
                  title={tip}
                  data-count={cell.count}
                  aria-label={tip}
                />
              );
            })}
          </div>

          <footer className={styles.footer}>
            <span className={styles.footerDates}>
              {rangeStart && rangeEnd
                ? `${formatDate(rangeStart)} – ${formatDate(rangeEnd)}`
                : ''}
            </span>
            <span className={styles.legend} aria-label="Intensity legend">
              <span className={styles.legendLabel}>Less</span>
              <span className={`${styles.legendCell} ${styles.lvl0}`} />
              <span className={`${styles.legendCell} ${styles.lvl1}`} />
              <span className={`${styles.legendCell} ${styles.lvl2}`} />
              <span className={`${styles.legendCell} ${styles.lvl3}`} />
              <span className={`${styles.legendCell} ${styles.lvl4}`} />
              <span className={styles.legendLabel}>More</span>
            </span>
          </footer>
        </>
      )}
    </section>
  );
};

export default Heatmap;
