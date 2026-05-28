import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import styles from './Tour.module.css';

const GAP = 12;          // px between target and tooltip
const PAD = 8;           // px outer margin from viewport edges
const POLL_MS = 50;
const POLL_TIMEOUT_MS = 2000;
const MOBILE_BP = 768;

const resolveTarget = (selector) => {
  if (!selector) return null;
  const nodes = document.querySelectorAll(selector);
  for (const n of nodes) {
    if (n.offsetParent !== null || n === document.body) return n;
    const rect = n.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) return n;
  }
  return null;
};

const useIsMobile = () => {
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.innerWidth <= MOBILE_BP
  );
  useEffect(() => {
    const onResize = () => setIsMobile(window.innerWidth <= MOBILE_BP);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return isMobile;
};

// Picks a placement for the tooltip and returns its pixel position.
//
// Key invariant: the axis *parallel* to the placement (top for top/bottom,
// left for left/right) is fixed to sit outside the target by `GAP` px.
// We only clamp the *perpendicular* axis to keep the card on-screen —
// clamping the parallel axis would push the card into the spotlit rect,
// which is the bug we're guarding against. If no placement leaves the
// card fully on-screen, we pick the one with the largest visible area.
const computeTooltipPos = (rect, cardSize, placement, vw, vh) => {
  const { width: cw, height: ch } = cardSize;
  const order = placement && placement !== 'center'
    ? [placement, 'bottom', 'top', 'right', 'left']
    : ['bottom', 'top', 'right', 'left'];
  const seen = new Set();

  const compute = (p) => {
    let top;
    let left;
    if (p === 'top') {
      top  = rect.top - ch - GAP;
      left = rect.left + rect.width / 2 - cw / 2;
    } else if (p === 'bottom') {
      top  = rect.bottom + GAP;
      left = rect.left + rect.width / 2 - cw / 2;
    } else if (p === 'left') {
      top  = rect.top + rect.height / 2 - ch / 2;
      left = rect.left - cw - GAP;
    } else { // right
      top  = rect.top + rect.height / 2 - ch / 2;
      left = rect.right + GAP;
    }
    // Clamp only the perpendicular axis.
    if (p === 'top' || p === 'bottom') {
      left = Math.max(PAD, Math.min(left, vw - cw - PAD));
    } else {
      top  = Math.max(PAD, Math.min(top,  vh - ch - PAD));
    }
    // How much of the card lands inside the viewport?
    const visW = Math.max(0, Math.min(left + cw, vw) - Math.max(left, 0));
    const visH = Math.max(0, Math.min(top + ch, vh) - Math.max(top, 0));
    const visibleRatio = (visW * visH) / Math.max(1, cw * ch);
    return { top, left, placement: p, visibleRatio };
  };

  let best = null;
  for (const p of order) {
    if (seen.has(p)) continue;
    seen.add(p);
    const c = compute(p);
    // 99% counts as "fully visible" — accounts for sub-pixel rounding.
    if (c.visibleRatio >= 0.99) return c;
    if (!best || c.visibleRatio > best.visibleRatio) best = c;
  }
  return best;
};

const Tour = ({ open, steps, onComplete, onSkip, onStepChange }) => {
  const [stepIndex, setStepIndex] = useState(0);
  const [rect, setRect] = useState(null);
  const [pos, setPos] = useState({ top: 0, left: 0, placement: 'bottom' });
  const [resolving, setResolving] = useState(false);
  const cardRef = useRef(null);
  const nextBtnRef = useRef(null);
  const titleBaseId = useId();
  const isMobile = useIsMobile();

  const safeSteps = Array.isArray(steps) ? steps : [];
  const step = safeSteps[stepIndex] || null;
  const isLast = stepIndex >= safeSteps.length - 1;
  const isFirst = stepIndex === 0;
  const isCenter = !step?.target || step?.placement === 'center';

  // Reset to step 0 when (re)opening.
  useEffect(() => {
    if (open) setStepIndex(0);
  }, [open]);

  // Notify host when the active step changes (so pages can react —
  // e.g. SolverX collapses its sidebar when a step isn't about it).
  useEffect(() => {
    if (!open) {
      onStepChange?.(null, -1);
      return;
    }
    onStepChange?.(step, stepIndex);
  }, [open, step, stepIndex, onStepChange]);

  // Scroll lock while open.
  useEffect(() => {
    if (!open) return undefined;
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { document.body.style.overflow = prev; };
  }, [open]);

  // Resolve current step's target (with polling for not-yet-mounted anchors).
  // When the target exists but is off-screen we smooth-scroll it into the
  // middle of the viewport before showing the tooltip, so the user can see
  // what's being explained instead of an empty spotlight.
  useEffect(() => {
    if (!open || !step) return undefined;
    if (isCenter) {
      setRect(null);
      setResolving(false);
      return undefined;
    }
    setResolving(true);
    let elapsed = 0;
    let cancelled = false;
    const tick = () => {
      if (cancelled) return;
      const el = resolveTarget(step.target);
      if (el) {
        const r = el.getBoundingClientRect();
        const vh = window.innerHeight;
        // Bring the target on-screen with a comfortable margin if it's
        // off-screen or near the edges.
        const margin = 80;
        const offScreen = r.bottom < margin || r.top > vh - margin;
        if (offScreen && typeof el.scrollIntoView === 'function') {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        setRect(r);
        setResolving(false);
        return;
      }
      elapsed += POLL_MS;
      if (elapsed >= POLL_TIMEOUT_MS) {
        // Give up on this step; auto-advance.
        setResolving(false);
        if (isLast) onComplete?.();
        else setStepIndex((i) => i + 1);
        return;
      }
      setTimeout(tick, POLL_MS);
    };
    tick();
    return () => { cancelled = true; };
  }, [open, step, isCenter, isLast, onComplete]);

  // Reposition on resize / scroll / target movement.
  useLayoutEffect(() => {
    if (!open || isCenter || !step?.target) return undefined;
    let rafId = 0;
    const recompute = () => {
      const el = resolveTarget(step.target);
      if (!el) return;
      setRect(el.getBoundingClientRect());
    };
    const onChange = () => {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(recompute);
    };
    window.addEventListener('resize', onChange);
    window.addEventListener('scroll', onChange, true);
    const el = resolveTarget(step.target);
    let ro;
    if (el && typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(onChange);
      ro.observe(el);
    }
    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('resize', onChange);
      window.removeEventListener('scroll', onChange, true);
      if (ro) ro.disconnect();
    };
  }, [open, step, isCenter]);

  // Compute tooltip position whenever rect or card size or viewport changes.
  useLayoutEffect(() => {
    if (!open) return;
    if (isCenter || !rect) return;
    const card = cardRef.current;
    if (!card) return;
    const cardSize = { width: card.offsetWidth, height: card.offsetHeight };
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    setPos(computeTooltipPos(rect, cardSize, step?.placement, vw, vh));
  }, [open, rect, step, isCenter, stepIndex]);

  // Focus the primary action when a step appears.
  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => nextBtnRef.current?.focus(), 0);
    return () => clearTimeout(t);
  }, [open, stepIndex]);

  const handleNext = useCallback(() => {
    if (isLast) onComplete?.();
    else setStepIndex((i) => i + 1);
  }, [isLast, onComplete]);

  const handleBack = useCallback(() => {
    setStepIndex((i) => Math.max(0, i - 1));
  }, []);

  // Keyboard: ESC ⇒ skip, Enter ⇒ advance.
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onSkip?.();
      } else if (e.key === 'Enter') {
        e.stopPropagation();
        handleNext();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onSkip, handleNext]);

  if (!open || !step) return null;

  const titleId = `${titleBaseId}-${stepIndex}`;

  // Cutout style: a transparent rect sized to the target, with a giant box-shadow that paints the dim.
  // For 'center' steps the cutout collapses and the dim layer covers the whole viewport.
  const cutoutStyle = isCenter || !rect
    ? null
    : {
        top: rect.top - 6,
        left: rect.left - 6,
        width: rect.width + 12,
        height: rect.height + 12,
      };

  // On mobile, render the card as a sheet pinned to whichever side of
  // the screen is *opposite* the target — that way the card never
  // overlaps what it's explaining.
  const sheetSide = isMobile && !isCenter && rect
    ? ((rect.top + rect.height / 2) < window.innerHeight / 2 ? 'bottom' : 'top')
    : null;

  const cardStyle = isMobile && !isCenter
    ? null  // mobile sheet position handled via CSS class
    : isCenter
      ? null  // centered via CSS class
      : { top: pos.top, left: pos.left };

  const cardClassName = [
    styles.card,
    isCenter ? styles.cardCenter : '',
    isMobile && !isCenter ? styles.cardSheet : '',
    sheetSide === 'top' ? styles.cardSheetTop : '',
    sheetSide === 'bottom' ? styles.cardSheetBottom : '',
    !isCenter && !isMobile ? styles[`cardPlacement_${pos.placement}`] || '' : '',
  ].join(' ').trim();

  return (
    <div
      className={styles.root}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
    >
      {isCenter || !cutoutStyle ? (
        <div className={styles.dimFull} aria-hidden="true" />
      ) : (
        <div className={styles.cutout} style={cutoutStyle} aria-hidden="true" />
      )}

      <div
        ref={cardRef}
        className={cardClassName}
        style={cardStyle || undefined}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={styles.cardHeader}>
          <span className={styles.stepBadge}>
            {stepIndex + 1} / {safeSteps.length}
          </span>
          <button
            type="button"
            className={styles.skipLink}
            onClick={onSkip}
          >
            Skip
          </button>
        </div>

        <h3 id={titleId} className={styles.title}>{step.title}</h3>
        <div className={styles.body}>{step.body}</div>

        <div className={styles.controls}>
          <button
            type="button"
            className={styles.btnGhost}
            onClick={handleBack}
            disabled={isFirst}
          >
            Back
          </button>
          <button
            ref={nextBtnRef}
            type="button"
            className={styles.btnPrimary}
            onClick={handleNext}
            disabled={resolving}
          >
            {isLast ? 'Got it' : 'Next'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default Tour;
