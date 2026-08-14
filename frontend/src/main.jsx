import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { captureAttribution } from './utils/attribution';
import { initAnalytics } from './services/analytics';
import './index.css';
import './styles/global.css';
import 'katex/dist/katex.min.css';

// Capture the marketing source from the landing URL before React mounts and
// any route redirect strips the query string.
captureAttribution();
// Load Umami (production only — no-op when VITE_UMAMI_WEBSITE_ID is unset).
initAnalytics();

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
