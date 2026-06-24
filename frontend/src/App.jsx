import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import AppRoutes from './routes/AppRoutes';
import PwaUpdatePrompt from './components/common/PwaUpdatePrompt/PwaUpdatePrompt';
import './App.css';

// The global sidebar (AppLayout) handles dashboard navigation, theme
// toggling, and sign-out. The old floating buttons are gone.
function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
      <PwaUpdatePrompt />
    </BrowserRouter>
  );
}

export default App;
