import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { AppShell } from '@/components/layout/AppShell';
import { Dashboard } from '@/pages/Dashboard';
import { LiveDrive } from '@/pages/LiveDrive';

export function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/trips/:tripId/live" element={<LiveDrive />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
