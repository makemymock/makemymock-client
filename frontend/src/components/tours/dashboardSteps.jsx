/* eslint-disable react-refresh/only-export-components */
// Co-locates the tiny `FinalStepBody` component with the tour-step array
// because the body is purely a presentational concern of the last step.
// Fast Refresh expects component-only modules; not a real risk for static
// tour data.
import { useSyncExternalStore } from 'react';

// AppLayout swaps the sidebar for a bottom nav at this width — keep the
// breakpoint here in sync with the rule in AppLayout.module.css.
const SIDEBAR_BREAKPOINT = '(min-width: 960px)';

const subscribeToSidebar = (callback) => {
  const mq = window.matchMedia(SIDEBAR_BREAKPOINT);
  mq.addEventListener('change', callback);
  return () => mq.removeEventListener('change', callback);
};
const getSidebarVisible = () => window.matchMedia(SIDEBAR_BREAKPOINT).matches;

// Inline tour-body that adapts the "sidebar / bottom nav" phrasing to whatever
// the user is actually looking at right now — so the same tour reads naturally
// at any window width without dropping in a parenthetical "(on mobile)".
const FinalStepBody = () => {
  const sidebarVisible = useSyncExternalStore(
    subscribeToSidebar, getSidebarVisible, () => true,
  );
  const navWord = sidebarVisible ? 'sidebar' : 'bottom nav';
  return (
    <>
      Use the {navWord} to jump into Practice, SolverX, Battle, or Analytics.
      Each one has its own short tour — replay any of them from the profile
      menu in the top‑right.
    </>
  );
};

export const dashboardTourSteps = [
  {
    title: 'Welcome to MakeMyMock 👋',
    body: 'Your day-to-day practice companion. A quick tour so you know where everything is.',
    placement: 'center',
  },
  {
    target: '[data-tour="dashboard.confidence"]',
    title: 'Your confidence',
    body: 'How confident you are across each subject, in one quick glance.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="dashboard.potd"]',
    title: 'Problem of the Day',
    body: 'A fresh question every day, picked to nudge one of your weaker topics.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="dashboard.notebook"]',
    title: 'Your notebook',
    body: 'Questions you’ve bookmarked to come back to. Open it anytime to revise.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="dashboard.performance"]',
    title: 'How you’re doing',
    body: 'Your accuracy at a glance, with the topics that need attention and the ones you’ve got down.',
    placement: 'top',
  },
  {
    target: '[data-tour="dashboard.side-panel"]',
    title: 'Activity, pending tests, recent battles',
    body: 'Your daily streak, any tests waiting for you, and your latest 1‑on‑1 matches — all in one place.',
    placement: 'left',
  },
  {
    title: 'That’s the dashboard',
    body: <FinalStepBody />,
    placement: 'center',
  },
];
