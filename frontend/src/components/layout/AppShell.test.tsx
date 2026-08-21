/**
 * The nav previously drew every link for everyone, so a driver saw "Users" and
 * "System" and got an API error on click. These assertions pin the negative
 * case — that the links a role may not use are simply not rendered.
 */
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { AppShell } from '@/components/layout/AppShell';
import { SessionProvider } from '@/lib/auth/SessionProvider';

const me = vi.hoisted(() => vi.fn());
vi.mock('@/lib/api/auth', () => ({ me }));

const STAFF_LINKS = ['Review Applications', 'Drivers', 'Vehicles', 'Trips'];
const ADMIN_LINKS = ['Users', 'System'];
const SHARED_LINKS = ['Dashboard', 'Driver Monitor', 'Become a Driver'];

function renderShell() {
  return render(
    <MemoryRouter>
      <SessionProvider>
        <AppShell>
          <p>page body</p>
        </AppShell>
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

describe('AppShell nav', () => {
  beforeEach(() => {
    me.mockReset();
  });

  // See RequireRole.test.tsx: no vitest `globals`, so unmount is manual.
  afterEach(cleanup);

  it('shows a driver only the shared links', async () => {
    me.mockResolvedValue(user('user'));
    renderShell();
    for (const link of SHARED_LINKS) {
      expect(await screen.findByRole('link', { name: link })).toBeDefined();
    }
    for (const link of [...STAFF_LINKS, ...ADMIN_LINKS]) {
      expect(screen.queryByRole('link', { name: link })).toBeNull();
    }
  });

  it('shows an employee the staff links but not the admin ones', async () => {
    me.mockResolvedValue(user('employee'));
    renderShell();
    for (const link of [...SHARED_LINKS, ...STAFF_LINKS]) {
      expect(await screen.findByRole('link', { name: link })).toBeDefined();
    }
    for (const link of ADMIN_LINKS) {
      expect(screen.queryByRole('link', { name: link })).toBeNull();
    }
  });

  it('shows an admin every link', async () => {
    me.mockResolvedValue(user('admin'));
    renderShell();
    for (const link of [...SHARED_LINKS, ...STAFF_LINKS, ...ADMIN_LINKS]) {
      expect(await screen.findByRole('link', { name: link })).toBeDefined();
    }
  });

  it('shows a signed-out visitor no nav links, but still renders the page', async () => {
    me.mockRejectedValue(new Error('Not authenticated'));
    renderShell();
    expect(await screen.findByText('page body')).toBeDefined();
    for (const link of [...SHARED_LINKS, ...STAFF_LINKS, ...ADMIN_LINKS]) {
      expect(screen.queryByRole('link', { name: link })).toBeNull();
    }
  });
});
