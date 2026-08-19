import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { AppShell } from '@/components/layout/AppShell';
import { DriverApplication } from '@/pages/DriverApplication';
import { DriverDashboard } from '@/pages/DriverDashboard';
import { DriverMonitor } from '@/pages/DriverMonitor';
import { EmployeeDrivers } from '@/pages/EmployeeDrivers';
import { EmployeeLogin } from '@/pages/EmployeeLogin';
import { EmployeeReviewDetail, EmployeeReviewQueue } from '@/pages/EmployeeReview';
import { Home } from '@/pages/Home';
import { LiveDrive } from '@/pages/LiveDrive';
import { Login } from '@/pages/Login';
import { Signup } from '@/pages/Signup';

export function App() {
  return (
    <BrowserRouter>
      <AppShell>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/dashboard" element={<DriverDashboard />} />
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />
          <Route path="/employee/login" element={<EmployeeLogin />} />
          <Route path="/employee/review" element={<EmployeeReviewQueue />} />
          <Route path="/employee/drivers" element={<EmployeeDrivers />} />
          <Route path="/employee/review/:driverId" element={<EmployeeReviewDetail />} />
          <Route path="/become-a-driver" element={<DriverApplication />} />
          <Route path="/trips/:tripId/live" element={<LiveDrive />} />
          <Route path="/driver-monitor" element={<DriverMonitor />} />
        </Routes>
      </AppShell>
    </BrowserRouter>
  );
}
