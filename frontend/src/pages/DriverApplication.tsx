import { useCallback, useEffect, useState } from 'react';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Panel } from '@/components/ui/Panel';
import {
  DOCUMENT_LABELS,
  createApplication,
  deleteDocument,
  getMyApplication,
  submitApplication,
  uploadDocument,
  type DocumentType,
  type DriverApplicationRead,
} from '@/lib/api/driverApplication';

const INPUT_CLASS =
  'rounded-lg border border-border-subtle bg-surface-raised px-4 py-2.5 text-content-primary placeholder:text-content-muted focus:border-accent focus:outline-none';
const BUTTON_CLASS =
  'rounded-lg bg-accent px-5 py-2.5 font-medium text-surface-base transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40';

const STATUS_TONE: Record<DriverApplicationRead['status'], BadgeTone> = {
  draft: 'neutral',
  pending: 'moderate',
  verified: 'low',
  rejected: 'critical',
};

const STATUS_LABEL: Record<DriverApplicationRead['status'], string> = {
  draft: 'Draft',
  pending: 'Pending review',
  verified: 'Verified',
  rejected: 'Rejected',
};

// Mirrors the backend's accepted types (app/core/documents.py). Advisory only —
// it filters the file picker; the server re-checks the bytes regardless.
const ACCEPT = 'image/png,application/pdf';

/** Statuses whose documents the applicant may still change (backend agrees). */
function isEditable(status: DriverApplicationRead['status']): boolean {
  return status === 'draft' || status === 'rejected';
}

function BasicInfoForm({ onCreated }: { onCreated: (application: DriverApplicationRead) => void }) {
  const [name, setName] = useState('');
  const [licenseNumber, setLicenseNumber] = useState('');
  const [dateOfBirth, setDateOfBirth] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      onCreated(
        await createApplication({
          name,
          license_number: licenseNumber,
          date_of_birth: dateOfBirth,
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the application');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Panel className="mt-6 p-6">
      <form onSubmit={(event) => void handleSubmit(event)} className="flex flex-col gap-3">
        <label className="text-sm text-content-secondary" htmlFor="name">
          Full name (as on your licence)
        </label>
        <input
          id="name"
          type="text"
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Asha Rao"
          autoComplete="name"
          className={INPUT_CLASS}
        />
        <label className="text-sm text-content-secondary" htmlFor="license">
          Driving licence number
        </label>
        <input
          id="license"
          type="text"
          required
          value={licenseNumber}
          onChange={(event) => setLicenseNumber(event.target.value)}
          placeholder="KA0120240000"
          className={INPUT_CLASS}
        />
        <label className="text-sm text-content-secondary" htmlFor="dob">
          Date of birth
        </label>
        <input
          id="dob"
          type="date"
          required
          value={dateOfBirth}
          onChange={(event) => setDateOfBirth(event.target.value)}
          className={INPUT_CLASS}
        />
        {error && <p className="text-sm text-risk-critical">{error}</p>}
        <button type="submit" disabled={submitting} className={`${BUTTON_CLASS} mt-2`}>
          {submitting ? 'Starting…' : 'Continue to documents'}
        </button>
      </form>
    </Panel>
  );
}

function DocumentSlot({
  documentType,
  required,
  uploaded,
  application,
  busy,
  onUpload,
  onDelete,
}: {
  documentType: DocumentType;
  required: number;
  uploaded: number;
  application: DriverApplicationRead;
  busy: boolean;
  onUpload: (documentType: DocumentType, file: File) => void;
  onDelete: (documentId: string) => void;
}) {
  const complete = uploaded >= required;
  const files = application.documents.filter((doc) => doc.document_type === documentType);
  const editable = isEditable(application.status);

  return (
    <Panel className="p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-medium text-content-primary">{DOCUMENT_LABELS[documentType]}</h3>
          <p className="text-xs text-content-muted">
            {uploaded} of {required} uploaded
          </p>
        </div>
        <Badge tone={complete ? 'low' : 'neutral'}>{complete ? 'Complete' : 'Needed'}</Badge>
      </div>

      {files.length > 0 && (
        <ul className="mt-3 flex flex-col gap-1">
          {files.map((doc, index) => (
            <li
              key={doc.id}
              className="flex items-center justify-between gap-2 text-sm text-content-secondary"
            >
              <span>
                File {index + 1} · {Math.round(doc.size_bytes / 1024)} KB
              </span>
              {editable && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onDelete(doc.id)}
                  className="text-xs text-risk-critical hover:underline disabled:opacity-40"
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {editable && !complete && (
        <label className="mt-3 block">
          <span className="sr-only">Upload {DOCUMENT_LABELS[documentType]}</span>
          <input
            type="file"
            accept={ACCEPT}
            disabled={busy}
            // Resetting `value` lets the same file be re-picked after a
            // failed upload, which otherwise fires no change event.
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = '';
              if (file) onUpload(documentType, file);
            }}
            className="block w-full text-sm text-content-secondary file:mr-3 file:rounded-md file:border-0 file:bg-surface-overlay file:px-3 file:py-1.5 file:text-sm file:text-content-primary hover:file:opacity-90"
          />
        </label>
      )}
    </Panel>
  );
}

export function DriverApplication() {
  const [application, setApplication] = useState<DriverApplicationRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMyApplication()
      .then((found) => {
        if (!cancelled) setApplication(found);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Could not load your application');
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Every mutating call returns the whole application, so the server's counts
  // replace local state wholesale rather than being incremented client-side.
  const run = useCallback(
    async (action: () => Promise<DriverApplicationRead>, fallback: string): Promise<void> => {
      setError(null);
      setBusy(true);
      try {
        setApplication(await action());
      } catch (err) {
        setError(err instanceof Error ? err.message : fallback);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  if (loading) {
    return <p className="mt-16 text-center text-content-secondary">Loading…</p>;
  }

  if (application === null) {
    return (
      <div className="mx-auto mt-12 max-w-lg">
        <h1 className="text-2xl font-semibold">Become a driver</h1>
        <p className="mt-2 text-sm text-content-secondary">
          Start with your basic details. You will upload 13 documents in the next step.
        </p>
        {error && <p className="mt-3 text-sm text-risk-critical">{error}</p>}
        <BasicInfoForm onCreated={setApplication} />
      </div>
    );
  }

  const totalRequired = application.requirements.reduce((sum, row) => sum + row.required, 0);
  const totalUploaded = application.requirements.reduce(
    (sum, row) => sum + Math.min(row.uploaded, row.required),
    0,
  );
  const editable = isEditable(application.status);

  return (
    <div className="mx-auto mt-12 max-w-3xl">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Driver application</h1>
        <Badge tone={STATUS_TONE[application.status]}>{STATUS_LABEL[application.status]}</Badge>
      </div>
      <p className="mt-2 text-sm text-content-secondary">
        {application.name} · {application.license_number}
      </p>

      {application.status === 'pending' && (
        <Panel className="mt-6 p-6">
          <h2 className="font-medium">Pending review</h2>
          <p className="mt-1 text-sm text-content-secondary">
            All {totalRequired} documents are in. A reviewer will check them and you will hear back
            once a decision is made. Your documents are locked while the review is in progress.
          </p>
        </Panel>
      )}

      {application.status === 'verified' && (
        <Panel className="mt-6 p-6">
          <h2 className="font-medium">Verified</h2>
          <p className="mt-1 text-sm text-content-secondary">
            Your application has been approved. You are cleared to drive.
          </p>
        </Panel>
      )}

      {application.status === 'rejected' && (
        <Panel className="mt-6 p-6">
          <h2 className="font-medium">Changes needed</h2>
          <p className="mt-1 text-sm text-content-secondary">
            Your application was rejected. Replace the documents that need fixing below, then submit
            it again.
          </p>
        </Panel>
      )}

      <div className="mt-6">
        <div className="flex items-center justify-between text-sm">
          <span className="text-content-secondary">Documents</span>
          <span className="text-content-muted">
            {totalUploaded} of {totalRequired}
          </span>
        </div>
        <div
          className="mt-2 h-2 overflow-hidden rounded-full bg-surface-overlay"
          role="progressbar"
          aria-valuenow={totalUploaded}
          aria-valuemin={0}
          aria-valuemax={totalRequired}
        >
          <div
            className="h-full bg-accent transition-all"
            style={{ width: `${(totalUploaded / totalRequired) * 100}%` }}
          />
        </div>
      </div>

      {error && <p className="mt-4 text-sm text-risk-critical">{error}</p>}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        {application.requirements.map((row) => (
          <DocumentSlot
            key={row.document_type}
            documentType={row.document_type}
            required={row.required}
            uploaded={row.uploaded}
            application={application}
            busy={busy}
            onUpload={(documentType, file) =>
              void run(() => uploadDocument(documentType, file), 'Upload failed')
            }
            onDelete={(documentId) =>
              void run(() => deleteDocument(documentId), 'Could not remove that file')
            }
          />
        ))}
      </div>

      {editable && (
        <div className="mt-6 flex items-center justify-end gap-3">
          {!application.is_complete && (
            <p className="text-sm text-content-muted">
              Upload all {totalRequired} documents to submit.
            </p>
          )}
          <button
            type="button"
            disabled={busy || !application.is_complete}
            onClick={() => void run(submitApplication, 'Could not submit the application')}
            className={BUTTON_CLASS}
          >
            {busy ? 'Working…' : 'Submit for review'}
          </button>
        </div>
      )}
    </div>
  );
}
