# ADR 0009 — Driver documents are stored on local disk, not object storage

- **Status:** Accepted
- **Date:** 2026-08-17
- **Milestone:** M-Auth-3

## Context

A driver application carries 13 files: 10 photos of the vehicle and applicant
(exterior, interior, plate, face) and 3 scanned documents (Aadhaar, insurance,
vehicle registration). They must be kept until a reviewer has looked at them,
and for some period afterwards.

The reflexive answer is S3 (or GCS/Azure Blob). That means an account,
credentials in the environment, a bucket policy, a client dependency, presigned
URL generation, and either a stub or live network calls in tests.

The deployment this system actually has is a **single backend container**
alongside Postgres — the same single-process topology ADR 0003 relies on. There
is no second worker that would need to read a file the first one wrote.

## Decision

**Documents are written to a local directory** (`settings.document_storage_dir`,
default `storage/documents/`), laid out as:

```
storage/documents/{driver_id}/{document_type}_{uuid4}.{png|pdf}
```

The database stores the path **relative to that root**, never an absolute one,
so the root can move without rewriting rows.

Safety properties come from not using client input to build paths, rather than
from sanitising it: the driver id is a server-side UUID, the document type is
validated against the `DocumentType` enum, and the basename is generated. The
uploaded filename is discarded. `app/core/documents.py` additionally re-resolves
every path and asserts it stays under the root.

Object storage will be introduced when either condition holds:

> The backend runs more than one instance, or instances are replaced often
> enough that a mounted volume stops being a dependable home for files that
> must outlive the container.

That migration is contained: `save_document` / `document_absolute_path` are the
only two functions that touch the filesystem, and `file_path` is already a
relative key — exactly the shape an object-store key takes.

## Consequences

**Positive**

- No cloud account, credentials, or client library needed to run the feature,
  including in tests, which write to a `tmp_path` root and assert on real files.
- One fewer failure mode in the upload path: no network call between accepting
  a file and having it stored.
- Uploads are directly inspectable during development.

**Negative**

- The directory must be a mounted volume in the container, or documents are
  lost on restart. This is a deployment requirement, documented here and in
  `Settings.document_storage_dir`, not something the code can enforce.
- No redundancy: the files live wherever that volume lives, with whatever
  backup that host provides. Acceptable while a rejected or lost application
  can be re-submitted; not acceptable once these are the system of record for
  a compliance obligation, which is a reason to revisit.
- Serving a document back requires the backend to read and stream it, rather
  than handing out a presigned URL.

## Alternatives considered

**Store the bytes in Postgres as `bytea`.** Rejected. It makes every backup and
every replication stream carry tens of megabytes per applicant, for data with
no relational character — the row already has everything worth querying.

**Adopt S3 now, "because production will need it."** Rejected on the same
grounds as ADR 0003's Redis decision: it adds a service and a credential to
solve a problem this topology does not yet have, and the condition that would
justify it can be stated precisely instead.
