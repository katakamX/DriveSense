import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Panel } from '@/components/ui/Panel';
import { login, logout } from '@/lib/api/auth';

const STAFF_ROLES = new Set(['employee', 'admin']);

export function EmployeeLogin() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const user = await login(email, password);
      if (!STAFF_ROLES.has(user.role)) {
        await logout();
        setError('This account is not authorized for employee access.');
        return;
      }
      void navigate('/');
    } catch {
      setError('Invalid email or password');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto mt-16 max-w-sm">
      <h1 className="text-2xl font-semibold">Employee sign in</h1>
      <Panel className="mt-6 p-6">
        <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-3">
          <label className="sr-only" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="Email"
            autoComplete="email"
            className="rounded-lg border border-border-subtle bg-surface-raised px-4 py-2.5 text-content-primary placeholder:text-content-muted focus:border-accent focus:outline-none"
          />
          <label className="sr-only" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Password"
            autoComplete="current-password"
            className="rounded-lg border border-border-subtle bg-surface-raised px-4 py-2.5 text-content-primary placeholder:text-content-muted focus:border-accent focus:outline-none"
          />
          {error && <p className="text-sm text-risk-critical">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="rounded-lg bg-accent px-5 py-2.5 font-medium text-surface-base transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="mt-4 text-center text-sm text-content-secondary">
          <Link to="/login" className="hover:underline">
            Back to sign in
          </Link>
        </p>
      </Panel>
    </div>
  );
}
