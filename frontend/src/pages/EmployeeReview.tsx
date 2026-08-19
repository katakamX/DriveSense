import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import { DOCUMENT_LABELS, type DriverApplicationRead } from '@/lib/api/driverApplication';
import {
  type DriverApplicationSummary,
  documentFileUrl,
  getApplication,
  listApplications,
  rejectApplication,
  verifyApplication,
} from '@/lib/api/driverReview';

const BUTTON_CLASS =
  'rounded-lg bg-accent px-5 py-2.5 font-medium text-surface-base transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40';

const STATUS_TONE: Record<DriverApplicationSummary['status'], BadgeTone> = {
  draft: 'neutral',
  pending: 'moderate',
  verified: 'low',
  rejected: 'critical',
};

const STATUS_LABEL: Record<DriverApplicationSummary['status'], string> = {
  draft: 'Draft',
  pending: 'Pending review',
  verified: 'Verified',
  rejected: 'Rejected',
};

const QUEUE_FILTERS = ['pending', 'verified', 'rejected', 'draft', 'all'] as const;
type QueueFilter = (typeof QUEUE_FILTERS)[number];

const FILTER_LABEL: Record<QueueFilter, string> = {
  pending: 'Pending',
  verified: 'Verified',
  rejected: 'Rejected',
  draft: 'Draft',
  all: 'All',
};

export function EmployeeReviewQueue() {
  const [filter, setFilter] = useState<QueueFilter>('pending');
  const [applications, setApplications] = useState<DriverApplicationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setApplications(null);
    setError(null);
    listApplications(filter === 'all' ? undefined : filter)
      .then((found) => {
        if (!cancelled) setApplications(found);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Could not load the queue');
      });
    return () => {
      cancelled = true;
    };
  }, [filter]);

  return (
    <div className="mx-auto mt-12 max-w-4xl">
      <h1 className="text-2xl font-semibold">Driver applications</h1>

      <div className="mt-4 flex items-center gap-1">
        {QUEUE_FILTERS.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => setFilter(option)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              filter === option
                ? 'bg-surface-overlay text-content-primary'
                : 'text-content-secondary hover:text-content-primary'
            }`}
          >
            {FILTER_LABEL[option]}
          </button>
        ))}
      </div>

      {error && <p className="mt-4 text-sm text-risk-critical">{error}</p>}

      {applications === null && !error && (
        <p className="mt-8 text-center text-content-secondary">Loading…</p>
      )}

      {applications !== null && applications.length === 0 && (
        <p className="mt-8 text-center text-content-secondary">No applications here.</p>
      )}

      {applications !== null && applications.length > 0 && (
        <Panel className="mt-6 divide-y divide-border-subtle">
          {applications.map((application) => (
            <Link
              key={application.id}
              to={`/employee/review/${application.id}`}
              className="flex items-center justify-between gap-4 px-5 py-4 transition-colors hover:bg-surface-overlay"
            >
              <div>
                <p className="font-medium text-content-primary">{application.name}</p>
                <p className="text-sm text-content-secondary">{application.license_number}</p>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-sm text-content-muted">
                  {application.documents_uploaded} of {application.documents_required} documents
                </span>
                <Badge tone={STATUS_TONE[application.status]}>
                  {STATUS_LABEL[application.status]}
                </Badge>
              </div>
            </Link>
          ))}
        </Panel>
      )}
    </div>
  );
}

function DocumentGrid({ application }: { application: DriverApplicationRead }) {
  return (
    <div className="mt-4 grid gap-3 sm:grid-cols-2">
      {application.documents.map((document) => {
        const url = documentFileUrl(application.id, document.id);
        const isImage = document.content_type.startsWith('image/');
        return (
          <Panel key={document.id} className="p-4">
            <p className="text-sm font-medium text-content-primary">
              {DOCUMENT_LABELS[document.document_type]}
            </p>
            <p className="text-xs text-content-muted">
              {Math.round(document.size_bytes / 1024)} KB
            </p>
            {isImage ? (
              <a href={url} target="_blank" rel="noreferrer">
                <img
                  src={url}
                  alt={DOCUMENT_LABELS[document.document_type]}
                  className="mt-2 h-40 w-full rounded-md border border-border-subtle object-cover"
                />
              </a>
            ) : (
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-block text-sm text-content-primary underline decoration-content-muted underline-offset-4 transition-colors hover:decoration-content-primary"
              >
                Open file
              </a>
            )}
          </Panel>
        );
      })}
    </div>
  );
}

export function EmployeeReviewDetail() {
  const { driverId } = useParams<{ driverId: string }>();
  const navigate = useNavigate();
  const [application, setApplication] = useState<DriverApplicationRead | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    if (!driverId) return;
    getApplication(driverId)
      .then(setApplication)
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : 'Could not load this application'),
      );
  }, [driverId]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = useCallback(
    async (action: (id: string) => Promise<DriverApplicationRead>) => {
      if (!driverId) return;
      setError(null);
      setBusy(true);
      try {
        setApplication(await action(driverId));
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Could not record the decision');
      } finally {
        setBusy(false);
      }
    },
    [driverId],
  );

  if (error && !application) {
    return (
      <div className="mx-auto mt-12 max-w-3xl">
        <p className="text-sm text-risk-critical">{error}</p>
        <button
          type="button"
          onClick={() => void navigate('/employee/review')}
          className="mt-4 text-sm text-content-primary underline decoration-content-muted underline-offset-4 transition-colors hover:decoration-content-primary"
        >
          Back to queue
        </button>
      </div>
    );
  }

  if (!application) {
    return <p className="mt-16 text-center text-content-secondary">Loading…</p>;
  }

  return (
    <div className="mx-auto mt-12 max-w-3xl">
      <Link to="/employee/review" className="text-sm text-content-secondary hover:underline">
        ← Back to queue
      </Link>

      <div className="mt-3 flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{application.name}</h1>
        <Badge tone={STATUS_TONE[application.status]}>{STATUS_LABEL[application.status]}</Badge>
      </div>
      <p className="mt-2 text-sm text-content-secondary">
        {application.license_number} · DOB {application.date_of_birth}
      </p>

      {error && <p className="mt-4 text-sm text-risk-critical">{error}</p>}

      <DocumentGrid application={application} />

      {application.status === 'pending' && (
        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            disabled={busy}
            onClick={() => void decide(rejectApplication)}
            className="rounded-lg border border-risk-critical px-5 py-2.5 font-medium text-risk-critical transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? 'Working…' : 'Reject'}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => void decide(verifyApplication)}
            className={BUTTON_CLASS}
          >
            {busy ? 'Working…' : 'Verify'}
          </button>
        </div>
      )}
    </div>
  );
}
