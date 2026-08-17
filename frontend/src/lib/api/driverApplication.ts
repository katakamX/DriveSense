/** Typed client for the driver-application endpoints (M-Auth-3). */

export const DOCUMENT_TYPES = [
  'exterior_photo',
  'interior_photo',
  'plate_photo',
  'face_photo',
  'aadhar',
  'insurance',
  'vehicle_registration',
] as const;

export type DocumentType = (typeof DOCUMENT_TYPES)[number];

export interface DocumentUploadRead {
  id: string;
  document_type: DocumentType;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
}

export interface DocumentRequirementRead {
  document_type: DocumentType;
  required: number;
  uploaded: number;
}

export interface DriverApplicationRead {
  id: string;
  name: string;
  license_number: string;
  date_of_birth: string;
  status: 'draft' | 'pending' | 'verified' | 'rejected';
  created_at: string;
  documents: DocumentUploadRead[];
  requirements: DocumentRequirementRead[];
  is_complete: boolean;
}

export interface BasicInfo {
  name: string;
  license_number: string;
  date_of_birth: string;
}

/** Human labels for the seven document types, used for both headings and errors. */
export const DOCUMENT_LABELS: Record<DocumentType, string> = {
  exterior_photo: 'Vehicle exterior',
  interior_photo: 'Vehicle interior',
  plate_photo: 'Number plate',
  face_photo: 'Your photo',
  aadhar: 'Aadhaar card',
  insurance: 'Insurance certificate',
  vehicle_registration: 'Vehicle registration (RC)',
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

/** The backend's `detail` string if there is one, else a status-code fallback. */
async function failure(response: Response): Promise<Error> {
  const detail = await response
    .json()
    .then((data: { detail?: string }) => data.detail)
    .catch(() => undefined);
  return new Error(detail ?? `Request failed with status ${response.status}`);
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: 'include', ...init });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export function createApplication(info: BasicInfo): Promise<DriverApplicationRead> {
  return request('/driver-applications', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(info),
  });
}

/** The current user's application, or `null` when they have not started one. */
export async function getMyApplication(): Promise<DriverApplicationRead | null> {
  const response = await fetch(`${API_BASE}/driver-applications/me`, { credentials: 'include' });
  if (response.status === 404) return null;
  if (!response.ok) throw await failure(response);
  return (await response.json()) as DriverApplicationRead;
}

export function uploadDocument(
  documentType: DocumentType,
  file: File,
): Promise<DriverApplicationRead> {
  const body = new FormData();
  body.append('document_type', documentType);
  body.append('file', file);
  // No explicit Content-Type: the browser has to set the multipart boundary.
  return request('/driver-applications/me/documents', { method: 'POST', body });
}

export function deleteDocument(documentId: string): Promise<DriverApplicationRead> {
  return request(`/driver-applications/me/documents/${documentId}`, { method: 'DELETE' });
}

export function submitApplication(): Promise<DriverApplicationRead> {
  return request('/driver-applications/me/submit', { method: 'POST' });
}
