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
import History from '../pages/history/History';
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
        path="/history"
        element={
          <ProtectedRoute>
            <History />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
};

export default AppRoutes;
