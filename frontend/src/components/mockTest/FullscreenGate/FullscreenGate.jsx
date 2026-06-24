import { useCallback, useEffect, useState } from 'react';
import Button from '../../common/Button/Button';
import {
  isFullscreen,
  fullscreenSupported,
  requestFullscreen,
  exitFullscreen,
  onFullscreenChange,
} from '../../../utils/fullscreen';
import styles from './FullscreenGate.module.css';

// Blocks its children behind a full-screen requirement: until the browser
// is in full screen, the student sees only the gate. Used by the drill
// (active test) so an attempt is always taken full screen — and if the
// student presses Esc mid-test, the gate re-appears and waits for them to
// re-enter before the questions come back.
//
// Entering full screen needs a live user gesture, so the gate's button is
// the gesture: we can't force it silently from an effect. If the browser
// has no Fullscreen API at all, the gate steps aside rather than locking
// the student out of their test.
const FullscreenGate = ({
  children,
  title = 'Full screen required',
  message = 'This drill runs in full screen so you stay focused, exam-style. Enter full screen to begin — press Esc any time to leave.',
  cta = 'Enter full screen',
}) => {
  const supported = fullscreenSupported();
  const [active, setActive] = useState(() => isFullscreen());
  const [error, setError] = useState('');

  useEffect(() => onFullscreenChange(() => setActive(isFullscreen())), []);

  // Leave full screen when the drill unmounts so the result page that
  // follows isn't stuck in the browser's full-screen mode.
  useEffect(() => () => { exitFullscreen(); }, []);

  const enter = useCallback(async () => {
    setError('');
    try {
      await requestFullscreen();
    } catch {
      setError('Your browser blocked full screen. Allow it and try again.');
    }
  }, []);

  if (!supported || active) return children;

  return (
    <div className={styles.gate} role="dialog" aria-modal="true" aria-labelledby="fsGateTitle">
      <div className={styles.card}>
        <div className={styles.icon} aria-hidden="true">⛶</div>
        <h2 id="fsGateTitle" className={styles.title}>{title}</h2>
        <p className={styles.message}>{message}</p>
        <Button variant="primary" fullWidth={false} onClick={enter}>{cta}</Button>
        {error ? <p className={styles.error}>{error}</p> : null}
      </div>
    </div>
  );
};

export default FullscreenGate;
