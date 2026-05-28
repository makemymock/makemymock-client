import { useMemo, useState } from 'react';
import styles from './ConfidenceTrophy.module.css';

// Tier → visual treatment. The CSS module owns the actual colour
// palette via the `tier_<key>` class; this map just picks the right
// suffix per tier index.
const TIER_VISUAL = {
  Doubter:     { key: 'doubter',     blurb: 'Just dipping a toe in.'    },
  Explorer:    { key: 'explorer',    blurb: 'Trying things out.'        },
  Confident:   { key: 'confident',   blurb: 'Finding your groove.'      },
  Focused:     { key: 'focused',     blurb: 'Committed practice.'       },
  Fearless:    { key: 'fearless',    blurb: 'High-performer territory.' },
  Unstoppable: { key: 'unstoppable', blurb: 'Elite — keep it up.'       },
};

// Trophy SVG. Strokes/fills use `currentColor` so the tier accent flows
// through automatically. Single inline svg, no external dependencies.
const TrophyIcon = ({ className }) => (
  <svg
    className={className}
    viewBox="0 0 64 64"
    fill="none"
    stroke="currentColor"
    strokeWidth="2.6"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {/* Cup body */}
    <path d="M18 10h28v14a14 14 0 0 1-28 0V10z" fill="currentColor" fillOpacity="0.18" />
    {/* Left handle */}
    <path d="M18 14H10v6a8 8 0 0 0 8 8" />
    {/* Right handle */}
    <path d="M46 14h8v6a8 8 0 0 1-8 8" />
    {/* Stem */}
    <path d="M32 38v8" />
    {/* Base plinth */}
    <path d="M22 46h20v6H22z" fill="currentColor" fillOpacity="0.22" />
    {/* Star detail on the cup */}
    <path
      d="M32 16l2.2 4.6 5 .7-3.6 3.5.9 5L32 27.5l-4.5 2.3.9-5-3.6-3.5 5-.7z"
      fill="currentColor"
      stroke="none"
    />
  </svg>
);

const formatPct = (n) => `${Math.round(n)}%`;

/**
 * Gamified confidence card — headline score, trophy badge for the
 * current tier, progress bar to the next tier, and a breakdown of the
 * 5 sub-scores that fed the headline.
 *
 * Props:
 *   data       — the ConfidenceResponse payload, or null while loading.
 *   compact    — when true, hides the sub-score breakdown; used in
 *                tight slots like the dashboard hero card.
 *   className  — optional extra class for the wrapper.
 */
const ConfidenceTrophy = ({ data, compact = false, className = '', dataTour }) => {
  const [showDetail, setShowDetail] = useState(false);

  const view = useMemo(() => {
    if (!data) return null;
    const tierName = data.tier?.name || 'Doubter';
    const visual = TIER_VISUAL[tierName] || TIER_VISUAL.Doubter;
    const score = Math.max(0, Math.min(100, Number(data.score) || 0));

    // Progress within the *current* tier band (0 → 100% of the band).
    const bandLo = data.tier?.min_score ?? 0;
    const bandHi = data.tier?.max_score ?? 100;
    const bandSize = Math.max(1, bandHi - bandLo);
    const bandPct = Math.max(0, Math.min(100, ((score - bandLo) / bandSize) * 100));

    const nextLabel = data.next_tier
      ? `${Math.max(0, Math.ceil(data.next_tier.min_score - score))} pts to ${data.next_tier.name}`
      : 'Top tier reached';

    return { tierName, visual, score, bandPct, nextLabel };
  }, [data]);

  if (!view) {
    return (
      <section
        className={`${styles.card} ${styles.skeleton} ${className}`}
        data-tour={dataTour}
      >
        <p className={styles.skeletonText}>Loading confidence…</p>
      </section>
    );
  }

  const { tierName, visual, score, bandPct, nextLabel } = view;
  const tierClass = styles[`tier_${visual.key}`] || '';

  return (
    <section
      className={`${styles.card} ${tierClass} ${compact ? styles.cardCompact : ''} ${className}`}
      aria-label={`Confidence score ${Math.round(score)} out of 100, trophy ${tierName}`}
      data-tour={dataTour}
    >
      <div className={styles.head}>
        <div className={styles.iconWrap}>
          <TrophyIcon className={styles.icon} />
        </div>
        <div className={styles.headMeta}>
          <span className={styles.tierLabel}>Trophy</span>
          <h3 className={styles.tierName}>{tierName}</h3>
          <p className={styles.blurb}>{visual.blurb}</p>
        </div>
        <div className={styles.scoreBlock}>
          <span className={styles.scoreEyebrow}>Confidence</span>
          <span className={styles.scoreValue}>{Math.round(score)}</span>
          <span className={styles.scoreOutOf}>/ 100</span>
        </div>
      </div>

      <div className={styles.progressRow}>
        <div className={styles.progressTrack} aria-hidden="true">
          <div
            className={styles.progressFill}
            style={{ width: `${bandPct}%` }}
          />
        </div>
        <span className={styles.progressLabel}>{nextLabel}</span>
      </div>

      {!compact ? (
        <>
          <button
            type="button"
            className={styles.detailToggle}
            onClick={() => setShowDetail((v) => !v)}
            aria-expanded={showDetail}
          >
            {showDetail ? 'Hide breakdown' : 'Show breakdown'}
            <span className={styles.detailChevron} aria-hidden="true">
              {showDetail ? '▾' : '▸'}
            </span>
          </button>

          {showDetail ? (
            <ul className={styles.subList}>
              {(data.sub_scores || []).map((s) => (
                <li key={s.key} className={styles.subRow}>
                  <div className={styles.subHead}>
                    <span className={styles.subLabel}>{s.label}</span>
                    <span className={styles.subMeta}>
                      <span className={styles.subValue}>
                        {Math.round(s.score)}
                      </span>
                      <span className={styles.subWeight}>
                        · {formatPct(s.weight * 100)} weight
                      </span>
                    </span>
                  </div>
                  <div className={styles.subTrack} aria-hidden="true">
                    <div
                      className={styles.subFill}
                      style={{ width: `${Math.max(0, Math.min(100, s.score))}%` }}
                    />
                  </div>
                  <p className={styles.subDetail}>{s.detail}</p>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      ) : null}
    </section>
  );
};

export default ConfidenceTrophy;
