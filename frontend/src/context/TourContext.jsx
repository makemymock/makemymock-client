import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { profileService } from '../services/profileService';

const TourContext = createContext(null);

export const TourProvider = ({ children }) => {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sessionDismissed, setSessionDismissed] = useState(() => new Set());
  const [forcedSlug, setForcedSlug] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const p = await profileService.getMyProfile();
        if (!cancelled) setProfile(p);
      } catch {
        if (!cancelled) setProfile(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const toursCompleted = useMemo(
    () => (profile?.tours_completed ?? []),
    [profile]
  );

  const isTourActive = useCallback(
    (slug) => {
      if (forcedSlug === slug) return true;
      if (loading || !profile) return false;
      if (toursCompleted.includes(slug)) return false;
      if (sessionDismissed.has(slug)) return false;
      return true;
    },
    [forcedSlug, loading, profile, toursCompleted, sessionDismissed]
  );

  const markComplete = useCallback((slug) => {
    // Optimistically close the tour so the UI feels instant.
    setSessionDismissed((prev) => {
      if (prev.has(slug)) return prev;
      const next = new Set(prev);
      next.add(slug);
      return next;
    });
    // Persist server-side in the background. On failure we keep the
    // session-dismissal so the tour doesn't re-fire in this tab; the
    // next reload will retry on its own.
    profileService
      .completeTour(slug)
      .then((updated) => setProfile(updated))
      .catch(() => {});
  }, []);

  const markDismissed = useCallback((slug) => {
    setSessionDismissed((prev) => {
      if (prev.has(slug)) return prev;
      const next = new Set(prev);
      next.add(slug);
      return next;
    });
  }, []);

  const forceReplay = useCallback((slug) => {
    setSessionDismissed((prev) => {
      if (!prev.has(slug)) return prev;
      const next = new Set(prev);
      next.delete(slug);
      return next;
    });
    setForcedSlug(slug);
  }, []);

  const consumeForce = useCallback((slug) => {
    setForcedSlug((current) => (current === slug ? null : current));
  }, []);

  const value = useMemo(
    () => ({
      profile,
      loading,
      toursCompleted,
      isTourActive,
      markComplete,
      markDismissed,
      forceReplay,
      consumeForce,
    }),
    [profile, loading, toursCompleted, isTourActive, markComplete, markDismissed, forceReplay, consumeForce]
  );

  return <TourContext.Provider value={value}>{children}</TourContext.Provider>;
};

export const useTourContext = () => useContext(TourContext);
