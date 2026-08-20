import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { RequireRole } from '@/components/auth/RequireRole';
import { AppShell } from '@/components/layout/AppShell';
import { SessionProvider } from '@/lib/auth/SessionProvider';
import { AdminSystem } from '@/pages/AdminSystem';
import { AdminUsers } from '@/pages/AdminUsers';
import { DriverApplication } from '@/pages/DriverApplication';
import { DriverDashboard } from '@/pages/DriverDashboard';
import { DriverLiveAnalysis } from '@/pages/DriverLiveAnalysis';
import { DriverMonitor } from '@/pages/DriverMonitor';
import { EmployeeDrivers } from '@/pages/EmployeeDrivers';
import { EmployeeLogin } from '@/pages/EmployeeLogin';
import { EmployeeReviewDetail, EmployeeReviewQueue } from '@/pages/EmployeeReview';
import { EmployeeTrips } from '@/pages/EmployeeTrips';
import { EmployeeVehicles } from '@/pages/EmployeeVehicles';
import { Home } from '@/pages/Home';
import { LiveDrive } from '@/pages/LiveDrive';
import { Login } from '@/pages/Login';
import { Signup } from '@/pages/Signup';
import { TripDetail } from '@/pages/TripDetail';

export function App() {
  return (
    <BrowserRouter>
      <SessionProvider>
        <AppShell>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/dashboard" element={<DriverDashboard />} />
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/employee/login" element={<EmployeeLogin />} />
            <Route
              path="/employee/review"
              element={
                <RequireRole allow="staff">
                  <EmployeeReviewQueue />
                </RequireRole>
              }
            />
            <Route
              path="/employee/drivers"
              element={
                <RequireRole allow="staff">
                  <EmployeeDrivers />
                </RequireRole>
              }
            />
            <Route
              path="/employee/vehicles"
              element={
                <RequireRole allow="staff">
                  <EmployeeVehicles />
                </RequireRole>
              }
            />
            <Route
              path="/employee/drivers/:driverId/analysis"
              element={
                <RequireRole allow="staff">
                  <DriverLiveAnalysis />
                </RequireRole>
              }
            />
            <Route
              path="/employee/trips"
              element={
                <RequireRole allow="staff">
                  <EmployeeTrips />
                </RequireRole>
              }
            />
            <Route
              path="/admin/users"
              element={
                <RequireRole allow="admin">
                  <AdminUsers />
                </RequireRole>
              }
            />
            <Route
              path="/admin/system"
              element={
                <RequireRole allow="admin">
                  <AdminSystem />
                </RequireRole>
              }
            />
            <Route
              path="/employee/review/:driverId"
              element={
                <RequireRole allow="staff">
                  <EmployeeReviewDetail />
                </RequireRole>
              }
            />
            <Route path="/become-a-driver" element={<DriverApplication />} />
            <Route path="/trips/:tripId" element={<TripDetail />} />
            <Route path="/trips/:tripId/live" element={<LiveDrive />} />
            <Route path="/driver-monitor" element={<DriverMonitor />} />
          </Routes>
        </AppShell>
      </SessionProvider>
    </BrowserRouter>
  );
}
