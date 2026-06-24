import { Navigate, Route, Routes } from 'react-router-dom';
import Landing from '../pages/landing/Landing';
import Signup from '../pages/signup/Signup';
import Login from '../pages/login/Login';
import Dashboard from '../pages/dashboard/Dashboard';
import ProfileSetup from '../pages/profile/ProfileSetup';
import UserProfile from '../pages/profile/UserProfile';
import TakeTest from '../pages/tests/TakeTest';
import Result from '../pages/tests/Result';
import BrowseQuestion from '../pages/tests/BrowseQuestion';
import Analytics from '../pages/analytics/Analytics';
import ChapterAnalytics from '../pages/analytics/ChapterAnalytics';
import TopicAnalytics from '../pages/analytics/TopicAnalytics';
import History from '../pages/history/History';
import BattleArena from '../pages/battle/BattleArena';
import BattleHistory from '../pages/battle/BattleHistory';
import BattleJoin from '../pages/battle/BattleJoin';
import Compete from '../pages/compete/Compete';
import ContestLobby from '../pages/compete/ContestLobby';
import ContestPlay from '../pages/compete/ContestPlay';
import ContestResult from '../pages/compete/ContestResult';
import SolverX from '../pages/solverx/SolverX';
import Practice from '../pages/practice/Practice';
import PatternPath from '../pages/learn/PatternPath';
import QuestionPath from '../pages/learn/QuestionPath';
import SolveQuestion from '../pages/learn/SolveQuestion';
import AppLayout from '../components/layout/AppLayout';
import ProtectedRoute from './ProtectedRoute';
import { tokenStorage } from '../utils/token';

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
            <ProfileSetup />
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
        <Route path="/profile" element={<UserProfile />} />
        {/* Practice hub — Drill session (mock test) + Patterns (pattern path). */}
        <Route path="/tests" element={<Practice />} />
        <Route path="/tests/browse/:questionId" element={<BrowseQuestion />} />
        <Route path="/tests/:sessionId" element={<TakeTest />} />
        <Route path="/tests/:sessionId/result" element={<Result />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/analytics/chapter/:chapterId" element={<ChapterAnalytics />} />
        <Route path="/analytics/topic/:topicId" element={<TopicAnalytics />} />
        <Route path="/history" element={<History />} />
        <Route path="/compete" element={<Compete />} />
        {/* Legacy /battle entry — keep the URL working but land on
            the new Compete > Battle tab. Deep links to /battle/play
            and /battle/history are unchanged. */}
        <Route path="/battle" element={<Navigate to="/compete?tab=battle" replace />} />
        <Route path="/battle/play" element={<BattleArena />} />
        <Route path="/battle/history" element={<BattleHistory />} />
        <Route path="/battle/join/:code" element={<BattleJoin />} />
        {/* Contest — lobby + fullscreen play + result. */}
        <Route path="/contest/:contestId" element={<ContestLobby />} />
        <Route path="/contest/:contestId/play" element={<ContestPlay />} />
        <Route path="/contest/:contestId/result" element={<ContestResult />} />
        <Route path="/solverx" element={<SolverX />} />
        {/* Pattern Path — Duolingo-style learning over mined reasoning
            patterns. The landing now lives inside the Practice hub as the
            Patterns tab; deep links to a chapter / pattern / question are
            unchanged. */}
        <Route path="/learn" element={<Navigate to="/tests?section=patterns" replace />} />
        <Route path="/learn/chapters/:chapter" element={<PatternPath />} />
        <Route path="/learn/patterns/:patternId" element={<QuestionPath />} />
        <Route path="/learn/questions/:questionId" element={<SolveQuestion />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export default AppRoutes;
