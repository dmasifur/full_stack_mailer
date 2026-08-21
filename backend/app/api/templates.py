from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.models.template import Template
from app.models.user import User
from app.schemas.campaign import TemplateResponse
from app.services.template_storage import (
    TemplateStorageError,
    delete_template,
    upload_template,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/templates", tags=["templates"])

MAX_TEMPLATE_BYTES = 5 * 1024 * 1024  # 5 MB — HTML files should never be larger


@router.post("", status_code=201, response_model=TemplateResponse)
async def upload_template_file(
    name: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Template:
    """
    Upload a Maizzle-compiled HTML file as a reusable template.
    Templates are shared across all users.
    """
    if not (file.filename or "").lower().endswith(".html"):
        raise HTTPException(status_code=400, detail="Only .html files are accepted.")

    html_bytes = await file.read()

    if len(html_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    if len(html_bytes) > MAX_TEMPLATE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum allowed size of {MAX_TEMPLATE_BYTES // 1024 // 1024} MB.",
        )

    try:
        storage_key = upload_template(
            html_bytes=html_bytes,
            original_filename=file.filename or "template.html",
        )
    except TemplateStorageError as exc:
        logger.exception("Template storage upload failed.")
        raise HTTPException(
            status_code=500, detail="Failed to store template."
        ) from exc

    template = Template(
        name=name,
        storage_key=storage_key,
        original_filename=file.filename or "template.html",
        uploaded_by=str(current_user.id),
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    logger.info(
        "Template uploaded. id=%s name=%s user=%s",
        template.id,
        name,
        current_user.email,
    )
    return template


@router.get("", response_model=list[TemplateResponse])
def list_templates(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Template]:
    """List all available templates (shared across users)."""
    return db.query(Template).order_by(Template.created_at.desc()).all()


@router.delete("/{template_id}", status_code=204)
def delete_template_record(
    template_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete a template. Only the uploader can delete their own templates.
    Also removes the file from R2 storage.
    """
    template = db.get(Template, template_id)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")

    if str(template.uploaded_by) != str(current_user.id):
        raise HTTPException(
            status_code=403, detail="Only the uploader can delete this template."
        )

    try:
        delete_template(template.storage_key)
    except TemplateStorageError:
        # Log but don't block DB cleanup — orphaned R2 objects are recoverable.
        logger.exception(
            "R2 delete failed for template %s — DB record will still be removed.",
            template_id,
        )

    db.delete(template)
    db.commit()

    logger.info("Template deleted. id=%s user=%s", template_id, current_user.email)
