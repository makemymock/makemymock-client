import React from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { tokenStorage } from '../utils/token';

const ProtectedRoute = ({ children }) => {
  const location = useLocation();
  const isAuthenticated = tokenStorage.isAuthenticated();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return children ? children : <Outlet />;
};

export default ProtectedRoute;
