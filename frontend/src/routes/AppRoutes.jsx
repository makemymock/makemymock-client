import { Navigate, Route, Routes } from 'react-router-dom';
import Landing from '../pages/landing/Landing';
import Signup from '../pages/signup/Signup';
import Login from '../pages/login/Login';
import Dashboard from '../pages/dashboard/Dashboard';
import ProfileSetup from '../pages/profile/ProfileSetup';
import TestsLaunch from '../pages/tests/TestsLaunch';
import TakeTest from '../pages/tests/TakeTest';
import Result from '../pages/tests/Result';
import BrowseQuestion from '../pages/tests/BrowseQuestion';
import Analytics from '../pages/analytics/Analytics';
import ChapterAnalytics from '../pages/analytics/ChapterAnalytics';
import TopicAnalytics from '../pages/analytics/TopicAnalytics';
import History from '../pages/history/History';
import BattleLaunch from '../pages/battle/BattleLaunch';
import BattleArena from '../pages/battle/BattleArena';
import BattleHistory from '../pages/battle/BattleHistory';
import SolverX from '../pages/solverx/SolverX';
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
        <Route path="/tests" element={<TestsLaunch />} />
        <Route path="/tests/browse/:questionId" element={<BrowseQuestion />} />
        <Route path="/tests/:sessionId" element={<TakeTest />} />
        <Route path="/tests/:sessionId/result" element={<Result />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/analytics/chapter/:chapterId" element={<ChapterAnalytics />} />
        <Route path="/analytics/topic/:topicId" element={<TopicAnalytics />} />
        <Route path="/history" element={<History />} />
        <Route path="/battle" element={<BattleLaunch />} />
        <Route path="/battle/play" element={<BattleArena />} />
        <Route path="/battle/history" element={<BattleHistory />} />
        <Route path="/solverx" element={<SolverX />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export default AppRoutes;
