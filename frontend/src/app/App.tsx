import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { AppShell } from '@/components/layout/AppShell';
import { Dashboard } from '@/pages/Dashboard';
import { DriverApplication } from '@/pages/DriverApplication';
import { DriverMonitor } from '@/pages/DriverMonitor';
import { EmployeeLogin } from '@/pages/EmployeeLogin';
import { EmployeeReviewDetail, EmployeeReviewQueue } from '@/pages/EmployeeReview';
import { LiveDrive } from '@/pages/LiveDrive';
import { Login } from '@/pages/Login';
import { Signup } from '@/pages/Signup';

export function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/employee/login" element={<EmployeeLogin />} />
          <Route path="/employee/review" element={<EmployeeReviewQueue />} />
          <Route path="/employee/review/:driverId" element={<EmployeeReviewDetail />} />
          <Route path="/become-a-driver" element={<DriverApplication />} />
          <Route path="/trips/:tripId/live" element={<LiveDrive />} />
          <Route path="/driver-monitor" element={<DriverMonitor />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
