// Local dev harness only (`pnpm dev`); the host loads src/Module.tsx.
import React from 'react';
import ReactDOM from 'react-dom/client';
import './i18n';
import ChannelsPage from './pages/ChannelsPage';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ChannelsPage />
  </React.StrictMode>
);
