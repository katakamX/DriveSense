import { Panel } from '@/components/ui/Panel';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

export function Login() {
  return (
    <div className="mx-auto mt-16 max-w-sm">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      <Panel className="mt-6 p-6">
        <a
          href={`${API_BASE}/auth/google/login`}
          className="flex w-full items-center justify-center gap-2 rounded-md border border-border-subtle bg-surface-overlay px-4 py-2.5 text-sm font-medium text-content-primary hover:bg-surface-raised"
        >
          Sign in with Google
        </a>
      </Panel>
    </div>
  );
}
