/**
 * The guard exists so a driver typing `/admin/users` gets a redirect rather
 * than a page that renders and then fails on a 403. The assertions below are
 * about *which* of those two happens, so each case checks both that the
 * guarded content is absent and that the redirect actually landed.
 */
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RequireRole } from '@/components/auth/RequireRole';
import { SessionProvider } from '@/lib/auth/SessionProvider';

const me = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api/auth', () => ({ me }));

function renderAt(path: string, allow: 'staff' | 'admin') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <SessionProvider>
        <Routes>
          <Route
            path={path}
            element={
              <RequireRole allow={allow}>
                <p>guarded content</p>
              </RequireRole>
            }
          />
          <Route path="/" element={<p>home page</p>} />
          <Route path="/login" element={<p>login page</p>} />
        </Routes>
      </SessionProvider>
    </MemoryRouter>,
  );
}

function user(role: string) {
  return {
    id: '1',
    email: 'someone@example.com',
    role,
    email_verified: true,
    created_at: '2026-01-01T00:00:00Z',
  };
}

describe('RequireRole', () => {
  beforeEach(() => {
    me.mockReset();
  });

  // The suite does not run with vitest `globals`, so testing-library's
  // automatic per-test unmount never registers — without this, every render
  // stays in the document and the queries below match the previous test's DOM.
  afterEach(cleanup);

  it('renders the page for a role that is allowed', async () => {
    me.mockResolvedValue(user('employee'));
    renderAt('/employee/drivers', 'staff');
    expect(await screen.findByText('guarded content')).toBeDefined();
  });

  it('lets an admin through a staff gate', async () => {
    me.mockResolvedValue(user('admin'));
    renderAt('/employee/drivers', 'staff');
    expect(await screen.findByText('guarded content')).toBeDefined();
  });

  it('redirects a driver away from a staff route instead of rendering it', async () => {
    me.mockResolvedValue(user('user'));
    renderAt('/employee/drivers', 'staff');
    expect(await screen.findByText('home page')).toBeDefined();
    expect(screen.queryByText('guarded content')).toBeNull();
  });

  it('redirects an employee away from an admin-only route', async () => {
    me.mockResolvedValue(user('employee'));
    renderAt('/admin/users', 'admin');
    expect(await screen.findByText('home page')).toBeDefined();
    expect(screen.queryByText('guarded content')).toBeNull();
  });

  it('sends a signed-out visitor to the login page', async () => {
    me.mockRejectedValue(new Error('Not authenticated'));
    renderAt('/admin/users', 'admin');
    expect(await screen.findByText('login page')).toBeDefined();
    expect(screen.queryByText('guarded content')).toBeNull();
  });

  it('renders nothing while the session is still resolving', () => {
    me.mockReturnValue(new Promise(() => {}));
    renderAt('/admin/users', 'admin');
    expect(screen.queryByText('guarded content')).toBeNull();
    expect(screen.queryByText('home page')).toBeNull();
    expect(screen.queryByText('login page')).toBeNull();
  });
});
