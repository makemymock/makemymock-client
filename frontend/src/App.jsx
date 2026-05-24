import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import AppRoutes from './routes/AppRoutes';
import DashboardFab from './components/common/DashboardFab/DashboardFab';
import './App.css';

function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
      <DashboardFab />
    </BrowserRouter>
  );
}

export default App;
