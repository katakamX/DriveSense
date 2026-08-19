import { useEffect, useState } from 'react';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { fetchUsers, updateUserRole, type AdminUser } from '@/lib/api/adminUsers';

const ROLES = ['user', 'employee', 'admin'] as const;

const ROLE_TONE: Record<string, BadgeTone> = {
  user: 'neutral',
  employee: 'moderate',
  admin: 'high',
};

export function AdminUsers() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    fetchUsers(controller.signal)
      .then((found) => setUsers(found))
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(err instanceof Error ? err.message : 'Could not load users');
        }
      });
    return () => controller.abort();
  }, []);

  const changeRole = async (userId: string, role: string): Promise<void> => {
    setPendingId(userId);
    setError(null);
    try {
      const updated = await updateUserRole(userId, role);
      setUsers((current) =>
        current ? current.map((u) => (u.id === userId ? updated : u)) : current,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not update role');
    } finally {
      setPendingId(null);
    }
  };

  return (
    <div>
      <h1 className="text-2xl font-semibold">Users</h1>
      <p className="mt-1 text-content-secondary">Promote or demote staff roles.</p>

      <Panel className="mt-6 overflow-hidden p-0">
        {error && <p className="p-5 text-risk-critical">{error}</p>}
        {!error && users !== null && users.length === 0 && (
          <p className="p-5 text-content-muted">No users found.</p>
        )}
        {!error && users !== null && users.length > 0 && (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-subtle text-left text-content-muted">
                <th className="px-5 py-3 font-medium">Email</th>
                <th className="px-5 py-3 font-medium">Verified</th>
                <th className="px-5 py-3 font-medium">Role</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-b border-border-subtle last:border-0">
                  <td className="px-5 py-3 text-content-primary">{user.email}</td>
                  <td className="px-5 py-3">
                    <Badge tone={user.email_verified ? 'low' : 'neutral'}>
                      {user.email_verified ? 'Verified' : 'Unverified'}
                    </Badge>
                  </td>
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2">
                      <Badge tone={ROLE_TONE[user.role] ?? 'neutral'}>{user.role}</Badge>
                      <select
                        value={user.role}
                        disabled={pendingId === user.id}
                        onChange={(event) => void changeRole(user.id, event.target.value)}
                        className="rounded-md border border-border-subtle bg-surface-base px-2 py-1 text-sm text-content-primary disabled:opacity-50"
                      >
                        {ROLES.map((role) => (
                          <option key={role} value={role}>
                            {role}
                          </option>
                        ))}
                      </select>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}
