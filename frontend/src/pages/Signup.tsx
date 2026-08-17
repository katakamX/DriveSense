import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { Panel } from '@/components/ui/Panel';
import { register, verifyOtp } from '@/lib/api/auth';

const INPUT_CLASS =
  'rounded-lg border border-border-subtle bg-surface-raised px-4 py-2.5 text-content-primary placeholder:text-content-muted focus:border-accent focus:outline-none';
const BUTTON_CLASS =
  'rounded-lg bg-accent px-5 py-2.5 font-medium text-surface-base transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40';

export function Signup() {
  const navigate = useNavigate();
  const [step, setStep] = useState<'register' | 'otp'>('register');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleRegister = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await register(email, password);
      setStep('otp');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setSubmitting(false);
    }
  };

  const handleVerify = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await verifyOtp(email, code);
      void navigate('/login');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid or expired code');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto mt-16 max-w-sm">
      <h1 className="text-2xl font-semibold">
        {step === 'register' ? 'Create account' : 'Verify your email'}
      </h1>
      <Panel className="mt-6 p-6">
        {step === 'register' ? (
          <form
            onSubmit={(event) => void handleRegister(event)}
            className="flex flex-col gap-3"
          >
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
              className={INPUT_CLASS}
            />
            <label className="sr-only" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              maxLength={72}
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Password (min. 8 characters)"
              autoComplete="new-password"
              className={INPUT_CLASS}
            />
            {error && <p className="text-sm text-risk-critical">{error}</p>}
            <button type="submit" disabled={submitting} className={BUTTON_CLASS}>
              {submitting ? 'Creating account…' : 'Create account'}
            </button>
          </form>
        ) : (
          <form onSubmit={(event) => void handleVerify(event)} className="flex flex-col gap-3">
            <p className="text-sm text-content-secondary">
              Enter the 6-digit code sent to {email}.
            </p>
            <label className="sr-only" htmlFor="otp">
              Verification code
            </label>
            <input
              id="otp"
              type="text"
              inputMode="numeric"
              required
              minLength={6}
              maxLength={6}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              placeholder="123456"
              autoComplete="one-time-code"
              className={`${INPUT_CLASS} text-center tracking-[0.5em]`}
            />
            {error && <p className="text-sm text-risk-critical">{error}</p>}
            <button type="submit" disabled={submitting} className={BUTTON_CLASS}>
              {submitting ? 'Verifying…' : 'Verify'}
            </button>
          </form>
        )}

        <p className="mt-4 text-center text-sm text-content-secondary">
          Already have an account?{' '}
          <Link to="/login" className="text-accent hover:underline">
            Sign in
          </Link>
        </p>
      </Panel>
    </div>
  );
}
