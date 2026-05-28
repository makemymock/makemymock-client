import { useCallback, useEffect, useRef } from 'react';
import { useTourContext } from '../context/TourContext';

export const useTour = (slug, steps) => {
  const ctx = useTourContext();
  const honouredForceRef = useRef(false);

  const open = ctx ? ctx.isTourActive(slug) : false;

  useEffect(() => {
    if (!ctx) return;
    if (open) {
      honouredForceRef.current = true;
    }
  }, [ctx, open]);

  useEffect(() => {
    if (!ctx) return undefined;
    return () => {
      if (honouredForceRef.current) {
        ctx.consumeForce(slug);
        honouredForceRef.current = false;
      }
    };
  }, [ctx, slug]);

  const onComplete = useCallback(() => {
    if (!ctx) return;
    ctx.consumeForce(slug);
    honouredForceRef.current = false;
    ctx.markComplete(slug);
  }, [ctx, slug]);

  const onSkip = useCallback(() => {
    if (!ctx) return;
    ctx.consumeForce(slug);
    honouredForceRef.current = false;
    ctx.markDismissed(slug);
  }, [ctx, slug]);

  return { open, steps, onComplete, onSkip };
};
