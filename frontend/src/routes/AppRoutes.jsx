import React, { Suspense, lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import Landing from '../pages/landing/Landing';
import Signup from '../pages/signup/Signup';
import Login from '../pages/login/Login';
import Dashboard from '../pages/dashboard/Dashboard';
import AppLayout from '../components/layout/AppLayout';
import ProtectedRoute from './ProtectedRoute';
import { tokenStorage } from '../utils/token';
import Loader from '../components/common/Loader/Loader';

// Lazy-load sub-routes and heavy features to minimize initial bundle size
const ProfileSetup = lazy(() => import('../pages/profile/ProfileSetup'));
const UserProfile = lazy(() => import('../pages/profile/UserProfile'));
const TakeTest = lazy(() => import('../pages/tests/TakeTest'));
const Result = lazy(() => import('../pages/tests/Result'));
const BrowseQuestion = lazy(() => import('../pages/tests/BrowseQuestion'));
const Analytics = lazy(() => import('../pages/analytics/Analytics'));
const ChapterAnalytics = lazy(() => import('../pages/analytics/ChapterAnalytics'));
const TopicAnalytics = lazy(() => import('../pages/analytics/TopicAnalytics'));
const History = lazy(() => import('../pages/history/History'));
const BattleArena = lazy(() => import('../pages/battle/BattleArena'));
const BattleHistory = lazy(() => import('../pages/battle/BattleHistory'));
const BattleJoin = lazy(() => import('../pages/battle/BattleJoin'));
const Compete = lazy(() => import('../pages/compete/Compete'));
const ContestLobby = lazy(() => import('../pages/compete/ContestLobby'));
const ContestPlay = lazy(() => import('../pages/compete/ContestPlay'));
const ContestResult = lazy(() => import('../pages/compete/ContestResult'));
const SolverX = lazy(() => import('../pages/solverx/SolverX'));
const Practice = lazy(() => import('../pages/practice/Practice'));
const PatternPath = lazy(() => import('../pages/learn/PatternPath'));
const QuestionPath = lazy(() => import('../pages/learn/QuestionPath'));
const SolveQuestion = lazy(() => import('../pages/learn/SolveQuestion'));

const Suspended = ({ children, fullscreen = false }) => (
  <Suspense fallback={<Loader fullscreen={fullscreen} cover={!fullscreen} label="Loading MakeMyMock…" />}>
    {children}
  </Suspense>
);

const RedirectIfAuthed = ({ children }) => {
  if (tokenStorage.isAuthenticated()) {
    return <Navigate to="/dashboard" replace />;
  }
  return children;
};

const AppRoutes = () => {
  return (
    <Routes>
      {/* ---- Public ---- */}
      <Route path="/" element={<Landing />} />
      <Route
        path="/signup"
        element={
          <RedirectIfAuthed>
            <Signup />
          </RedirectIfAuthed>
        }
      />
      <Route
        path="/login"
        element={
          <RedirectIfAuthed>
            <Login />
          </RedirectIfAuthed>
        }
      />

      {/* Profile setup runs before the layout so it isn't shown inside
          the dashboard chrome (the user doesn't yet have a profile). */}
      <Route
        path="/profile/setup"
        element={
          <ProtectedRoute>
            <Suspended fullscreen>
              <ProfileSetup />
            </Suspended>
          </ProtectedRoute>
        }
      />

      {/* ---- Protected pages, all wrapped in the global AppLayout.
            Active test / battle and SolverX bypass the chrome via the
            FULLSCREEN_RE inside AppLayout itself. ---- */}
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/dashboard" element={<Dashboard />} />
        <Route
          path="/profile"
          element={
            <Suspended>
              <UserProfile />
            </Suspended>
          }
        />
        {/* Practice hub — Drill session (mock test) + Patterns (pattern path). */}
        <Route
          path="/tests"
          element={
            <Suspended>
              <Practice />
            </Suspended>
          }
        />
        <Route
          path="/tests/browse/:questionId"
          element={
            <Suspended>
              <BrowseQuestion />
            </Suspended>
          }
        />
        <Route
          path="/tests/:sessionId"
          element={
            <Suspended fullscreen>
              <TakeTest />
            </Suspended>
          }
        />
        <Route
          path="/tests/:sessionId/result"
          element={
            <Suspended>
              <Result />
            </Suspended>
          }
        />
        <Route
          path="/analytics"
          element={
            <Suspended>
              <Analytics />
            </Suspended>
          }
        />
        <Route
          path="/analytics/chapter/:chapterId"
          element={
            <Suspended>
              <ChapterAnalytics />
            </Suspended>
          }
        />
        <Route
          path="/analytics/topic/:topicId"
          element={
            <Suspended>
              <TopicAnalytics />
            </Suspended>
          }
        />
        <Route
          path="/history"
          element={
            <Suspended>
              <History />
            </Suspended>
          }
        />
        <Route
          path="/compete"
          element={
            <Suspended>
              <Compete />
            </Suspended>
          }
        />
        {/* Legacy /battle entry — keep the URL working but land on
            the new Compete > Battle tab. Deep links to /battle/play
            and /battle/history are unchanged. */}
        <Route path="/battle" element={<Navigate to="/compete?tab=battle" replace />} />
        <Route
          path="/battle/play"
          element={
            <Suspended fullscreen>
              <BattleArena />
            </Suspended>
          }
        />
        <Route
          path="/battle/history"
          element={
            <Suspended>
              <BattleHistory />
            </Suspended>
          }
        />
        <Route
          path="/battle/join/:code"
          element={
            <Suspended>
              <BattleJoin />
            </Suspended>
          }
        />
        {/* Contest — lobby + fullscreen play + result. */}
        <Route
          path="/contest/:contestId"
          element={
            <Suspended>
              <ContestLobby />
            </Suspended>
          }
        />
        <Route
          path="/contest/:contestId/play"
          element={
            <Suspended fullscreen>
              <ContestPlay />
            </Suspended>
          }
        />
        <Route
          path="/contest/:contestId/result"
          element={
            <Suspended>
              <ContestResult />
            </Suspended>
          }
        />
        <Route
          path="/solverx"
          element={
            <Suspended fullscreen>
              <SolverX />
            </Suspended>
          }
        />
        {/* Pattern Path — Duolingo-style learning over mined reasoning
            patterns. The landing now lives inside the Practice hub as the
            Patterns tab; deep links to a chapter / pattern / question are
            unchanged. */}
        <Route path="/learn" element={<Navigate to="/tests?section=patterns" replace />} />
        <Route
          path="/learn/chapters/:chapter"
          element={
            <Suspended>
              <PatternPath />
            </Suspended>
          }
        />
        <Route
          path="/learn/patterns/:patternId"
          element={
            <Suspended>
              <QuestionPath />
            </Suspended>
          }
        />
        <Route
          path="/learn/questions/:questionId"
          element={
            <Suspended>
              <SolveQuestion />
            </Suspended>
          }
        />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export default AppRoutes;
