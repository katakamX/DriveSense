import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { AppShell } from '@/components/layout/AppShell';
import { Dashboard } from '@/pages/Dashboard';
import { DriverMonitor } from '@/pages/DriverMonitor';
import { LiveDrive } from '@/pages/LiveDrive';

export function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/trips/:tripId/live" element={<LiveDrive />} />
          <Route path="/driver-monitor" element={<DriverMonitor />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
