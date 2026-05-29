import styles from './Podium.module.css';

// Display the top 3 contest finishers as a podium — 2nd on the left,
// 1st centred and tallest, 3rd on the right (the classic competition
// arrangement). Each block carries the rank medal, username, score,
// and time taken. `youUserId` highlights the current user's block.
//
// `rows` should be the leaderboard rows in rank order. If fewer than
// 3 rows are present the missing slots render as muted placeholders
// so the podium silhouette stays intact.

const ORDER = [1, 0, 2]; // visual order: 2nd, 1st, 3rd

const fmtTime = (s) => {
  if (!s && s !== 0) return '—';
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}m ${sec.toString().padStart(2, '0')}s`;
};

const Podium = ({ rows = [], youUserId = null }) => {
  // Pad to 3 slots so the layout doesn't collapse with 1 or 2 entries.
  const top3 = [0, 1, 2].map((i) => rows[i] || null);

  return (
    <div className={styles.podium} aria-label="Top 3 finishers">
      {ORDER.map((rankIdx) => {
        const row = top3[rankIdx];
        const rank = rankIdx + 1;
        const empty = !row;
        const isYou = !empty && (
          row.is_you || (youUserId && row.user_id === youUserId)
        );
        return (
          <div
            key={rank}
            className={`${styles.slot} ${styles[`rank_${rank}`]} ${empty ? styles.empty : ''}`}
          >
            <div className={styles.medal}>{rank}</div>
            <p className={styles.name}>
              {empty ? '—' : row.username}
              {isYou ? <span className={styles.youTag}>You</span> : null}
            </p>
            <p className={styles.score}>
              {empty ? '—' : row.score.toFixed(1)}
              {!empty ? <span className={styles.scoreUnit}>pts</span> : null}
            </p>
            <p className={styles.time}>
              {empty ? '' : `${row.correct_count} correct · ${fmtTime(row.time_taken_seconds)}`}
            </p>
            <div className={styles.bar} aria-hidden="true" />
          </div>
        );
      })}
    </div>
  );
};

export default Podium;
