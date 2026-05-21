import { useEffect, useRef, useState } from 'react';
import styles from './Timer.module.css';

function fmt(secs) {
  const total = Math.max(0, Math.floor(secs));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const hh = h.toString().padStart(2, '0');
  const mm = m.toString().padStart(2, '0');
  const ss = s.toString().padStart(2, '0');
  return h > 0 ? `${hh}:${mm}:${ss}` : `${mm}:${ss}`;
}

// `startedAtMs` is a millisecond epoch captured on the client (Date.now())
// when the exam page first mounted, and persisted in sessionStorage so
// refreshes resume from the same start. Decoupled from server clocks /
// timezones — the timer just counts down `totalSeconds` from that point.
const Timer = ({ startedAtMs, totalSeconds, onExpire }) => {
  const start = Number.isFinite(startedAtMs) ? startedAtMs : Date.now();
  const total = Number.isFinite(totalSeconds) && totalSeconds > 0 ? totalSeconds : 0;

  const [remaining, setRemaining] = useState(() =>
    Math.max(0, total - (Date.now() - start) / 1000),
  );
  const firedRef = useRef(false);

  useEffect(() => {
    if (total <= 0) return undefined;
    const tick = () => {
      const r = Math.max(0, total - (Date.now() - start) / 1000);
      setRemaining(r);
      if (r <= 0 && !firedRef.current) {
        firedRef.current = true;
        if (typeof onExpire === 'function') onExpire();
      }
    };
    tick();
    const id = setInterval(tick, 500);
    return () => clearInterval(id);
  }, [start, total, onExpire]);

  const warn = remaining <= 60 && remaining > 0;
  const out = remaining <= 0;

  return (
    <div
      className={`${styles.timer} ${warn ? styles.warn : ''} ${out ? styles.out : ''}`}
      role="timer"
      aria-live="off"
    >
      <span className={styles.icon} aria-hidden="true">⏱</span>
      <span className={styles.value}>{fmt(remaining)}</span>
    </div>
  );
};

export default Timer;
