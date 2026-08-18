"""The driver-facing application flow: basic info, 13 documents, submit for review.

Driver-facing, not staff tooling — every route here is gated on
`get_current_user` (any logged-in user) rather than `require_staff`, and
resolves the application from `Driver.user_id == current_user.id`. There is no
route that takes someone else's driver id, which is what keeps one applicant
out of another's documents.

Reviewing an application (verified/rejected) is M-Auth-4's staff-side flow;
this module only ever moves it draft -> pending.
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user
from app.core.documents import DocumentValidationError, save_document
from app.db.models import (
    REQUIRED_DOCUMENT_COUNTS,
    DocumentType,
    DocumentUpload,
    Driver,
    DriverStatus,
    User,
)
from app.db.session import get_db
from app.schemas.driver_application import (
    DocumentRequirementRead,
    DocumentUploadRead,
    DriverApplicationCreate,
    DriverApplicationRead,
)

router = APIRouter(prefix="/driver-applications", tags=["driver-applications"])

# Statuses whose documents the applicant may still change. A rejected
# application is editable on purpose: fixing the blurry photo a reviewer
# complained about and resubmitting is the point of telling them it was
# rejected. Pending and verified are frozen — a reviewer must be looking at
# the same files the decision will be recorded against.
_EDITABLE_STATUSES = frozenset({DriverStatus.DRAFT, DriverStatus.REJECTED})


def build_application_read(
    driver: Driver, documents: list[DocumentUpload]
) -> DriverApplicationRead:
    uploaded_counts: dict[str, int] = {}
    for document in documents:
        uploaded_counts[document.document_type] = uploaded_counts.get(document.document_type, 0) + 1

    requirements = [
        DocumentRequirementRead(
            document_type=document_type.value,
            required=required,
            uploaded=uploaded_counts.get(document_type.value, 0),
        )
        for document_type, required in REQUIRED_DOCUMENT_COUNTS.items()
    ]
    return DriverApplicationRead(
        id=driver.id,
        name=driver.name,
        license_number=driver.license_number,
        date_of_birth=driver.date_of_birth,
        status=driver.status,
        created_at=driver.created_at,
        documents=[DocumentUploadRead.model_validate(document) for document in documents],
        requirements=requirements,
        is_complete=all(row.uploaded >= row.required for row in requirements),
    )


async def _load_application(db: AsyncSession, user: User) -> Driver:
    """The current user's application, or 404 if they have not started one."""
    result = await db.execute(select(Driver).where(Driver.user_id == user.id))
    driver = result.scalar_one_or_none()
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No driver application found")
    return driver


async def load_documents(db: AsyncSession, driver_id: uuid.UUID) -> list[DocumentUpload]:
    result = await db.execute(
        select(DocumentUpload)
        .where(DocumentUpload.driver_id == driver_id)
        .order_by(DocumentUpload.uploaded_at)
    )
    return list(result.scalars().all())


@router.post("", response_model=DriverApplicationRead, status_code=status.HTTP_201_CREATED)
async def create_application(
    payload: DriverApplicationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverApplicationRead:
    """Start an application. One per user, enforced by `drivers.user_id`'s unique index."""
    driver = Driver(**payload.model_dump(), user_id=user.id, status=DriverStatus.DRAFT)
    db.add(driver)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        # Either this user already has an application, or the licence number
        # belongs to an existing driver. Both are the applicant's problem to
        # resolve, and neither should leak which other record it collided with.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An application already exists for this user or licence number",
        ) from exc
    await db.refresh(driver)
    return build_application_read(driver, [])


@router.get("/me", response_model=DriverApplicationRead)
async def get_my_application(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DriverApplicationRead:
    driver = await _load_application(db, user)
    return build_application_read(driver, await load_documents(db, driver.id))


@router.post(
    "/me/documents", response_model=DriverApplicationRead, status_code=status.HTTP_201_CREATED
)
async def upload_document(
    document_type: DocumentType = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverApplicationRead:
    """Add one file to the application, returning its full refreshed state.

    Returning the whole application rather than just the new row means the
    client's progress display cannot drift from the server's count — it is
    told what the server now holds after every upload.
    """
    driver = await _load_application(db, user)
    if driver.status not in _EDITABLE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Application is {driver.status} and can no longer be changed"
        )

    documents = await load_documents(db, driver.id)
    limit = REQUIRED_DOCUMENT_COUNTS[document_type]
    already = sum(1 for document in documents if document.document_type == document_type.value)
    if already >= limit:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"All {limit} {document_type.value} file(s) already uploaded; delete one to replace it",
        )

    data = await file.read()
    try:
        stored = save_document(driver.id, document_type, file.content_type, data)
    except DocumentValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    upload = DocumentUpload(
        driver_id=driver.id,
        document_type=document_type.value,
        file_path=stored.file_path,
        content_type=stored.content_type,
        size_bytes=stored.size_bytes,
    )
    db.add(upload)
    await db.commit()
    await db.refresh(upload)
    return build_application_read(driver, [*documents, upload])


@router.delete("/me/documents/{document_id}", response_model=DriverApplicationRead)
async def delete_document(
    document_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DriverApplicationRead:
    """Remove one uploaded file so the applicant can replace it.

    The file on disk is left in place: a delete here is a correction during
    form-filling, and an orphaned blob costs less than a request that half
    fails (row gone, file gone, transaction rolled back). Reaping them is a
    housekeeping job, not part of this request.
    """
    driver = await _load_application(db, user)
    if driver.status not in _EDITABLE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Application is {driver.status} and can no longer be changed"
        )

    document = await db.get(DocumentUpload, document_id)
    # A document belonging to someone else is reported as missing, not as
    # forbidden — "wrong owner" and "no such id" are the same answer here.
    if document is None or document.driver_id != driver.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    await db.delete(document)
    await db.commit()
    return build_application_read(driver, await load_documents(db, driver.id))


@router.post("/me/submit", response_model=DriverApplicationRead)
async def submit_application(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> DriverApplicationRead:
    """Move a complete application to `pending` review."""
    driver = await _load_application(db, user)
    if driver.status not in _EDITABLE_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Application is already {driver.status}")

    documents = await load_documents(db, driver.id)
    application = build_application_read(driver, documents)
    if not application.is_complete:
        missing = ", ".join(
            f"{row.document_type} ({row.uploaded}/{row.required})"
            for row in application.requirements
            if row.uploaded < row.required
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Missing required documents: {missing}")

    driver.status = DriverStatus.PENDING
    await db.commit()
    await db.refresh(driver)
    return build_application_read(driver, documents)
