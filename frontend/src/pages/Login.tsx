import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Panel } from '@/components/ui/Panel';
import { login } from '@/lib/api/auth';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export function Login() {
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
      await login(email, password);
      void navigate('/');
    } catch {
      setError('Invalid email or password');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto mt-16 max-w-sm">
      <h1 className="text-2xl font-semibold">Sign in</h1>
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

        <div className="my-4 flex items-center gap-3 text-xs text-content-muted">
          <span className="h-px flex-1 bg-border-subtle" />
          or
          <span className="h-px flex-1 bg-border-subtle" />
        </div>

        <a
          href={`${API_BASE}/auth/google/login`}
          className="flex w-full items-center justify-center gap-2 rounded-md border border-border-subtle bg-surface-overlay px-4 py-2.5 text-sm font-medium text-content-primary hover:bg-surface-raised"
        >
          Sign in with Google
        </a>

        <p className="mt-4 text-center text-sm text-content-secondary">
          No account?{' '}
          <Link
            to="/signup"
            className="text-content-primary underline decoration-content-muted underline-offset-4 transition-colors hover:decoration-content-primary"
          >
            Sign up
          </Link>
        </p>
      </Panel>

      <p className="mt-6 text-center text-xs text-content-muted">
        <Link to="/employee/login" className="hover:underline">
          Employee login
        </Link>
      </p>
    </div>
  );
}
