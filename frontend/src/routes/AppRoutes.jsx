import { Navigate, Route, Routes } from 'react-router-dom';
import Landing from '../pages/landing/Landing';
import Signup from '../pages/signup/Signup';
import Login from '../pages/login/Login';
import Dashboard from '../pages/dashboard/Dashboard';
import ProfileSetup from '../pages/profile/ProfileSetup';
import TestsLaunch from '../pages/tests/TestsLaunch';
import TakeTest from '../pages/tests/TakeTest';
import Result from '../pages/tests/Result';
import Analytics from '../pages/analytics/Analytics';
import ChapterAnalytics from '../pages/analytics/ChapterAnalytics';
import TopicAnalytics from '../pages/analytics/TopicAnalytics';
import History from '../pages/history/History';
import BattleLaunch from '../pages/battle/BattleLaunch';
import BattleArena from '../pages/battle/BattleArena';
import BattleHistory from '../pages/battle/BattleHistory';
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
      <Route
        path="/profile/setup"
        element={
          <ProtectedRoute>
            <ProfileSetup />
          </ProtectedRoute>
        }
      />
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <Dashboard />
          </ProtectedRoute>
        }
      />
      {/* Mock-test section — URL-only access for now (no buttons). */}
      <Route
        path="/tests"
        element={
          <ProtectedRoute>
            <TestsLaunch />
          </ProtectedRoute>
        }
      />
      <Route
        path="/tests/:sessionId"
        element={
          <ProtectedRoute>
            <TakeTest />
          </ProtectedRoute>
        }
      />
      <Route
        path="/tests/:sessionId/result"
        element={
          <ProtectedRoute>
            <Result />
          </ProtectedRoute>
        }
      />
      <Route
        path="/analytics"
        element={
          <ProtectedRoute>
            <Analytics />
          </ProtectedRoute>
        }
      />
      <Route
        path="/analytics/chapter/:chapterId"
        element={
          <ProtectedRoute>
            <ChapterAnalytics />
          </ProtectedRoute>
        }
      />
      <Route
        path="/analytics/topic/:topicId"
        element={
          <ProtectedRoute>
            <TopicAnalytics />
          </ProtectedRoute>
        }
      />
      <Route
        path="/history"
        element={
          <ProtectedRoute>
            <History />
          </ProtectedRoute>
        }
      />
      {/* 1-vs-1 Battle Arena */}
      <Route
        path="/battle"
        element={
          <ProtectedRoute>
            <BattleLaunch />
          </ProtectedRoute>
        }
      />
      <Route
        path="/battle/play"
        element={
          <ProtectedRoute>
            <BattleArena />
          </ProtectedRoute>
        }
      />
      <Route
        path="/battle/history"
        element={
          <ProtectedRoute>
            <BattleHistory />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export default AppRoutes;
