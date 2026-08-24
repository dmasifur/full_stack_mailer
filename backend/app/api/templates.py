from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, get_db
from app.models.template import Template
from app.models.user import User
from app.schemas.campaign import (
    TemplateHtmlCreate,
    TemplateHtmlResponse,
    TemplateHtmlUpdate,
    TemplateResponse,
)
from app.services.template_storage import (
    TemplateStorageError,
    delete_template,
    fetch_template,
    upload_template,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/templates", tags=["templates"])

MAX_TEMPLATE_BYTES = 5 * 1024 * 1024  # 5 MB — HTML files should never be larger


def _slug(name: str) -> str:
    """A filename for a template that was typed, not uploaded."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{slug or 'template'}.html"


def _assert_within_size_limit(html_bytes: bytes) -> None:
    if len(html_bytes) > MAX_TEMPLATE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum allowed size of {MAX_TEMPLATE_BYTES // 1024 // 1024} MB.",
        )


def _store(html_bytes: bytes, filename: str) -> str:
    try:
        return upload_template(html_bytes=html_bytes, original_filename=filename)
    except TemplateStorageError as exc:
        logger.exception("Template storage upload failed.")
        raise HTTPException(
            status_code=500, detail="Failed to store template."
        ) from exc


def _get_own_template_or_404(
    template_id: str, db: Session, current_user: User
) -> Template:
    template = db.get(Template, template_id)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")

    if str(template.uploaded_by) != str(current_user.id):
        raise HTTPException(
            status_code=403, detail="Only the uploader can modify this template."
        )

    return template


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

    _assert_within_size_limit(html_bytes)

    storage_key = _store(html_bytes, file.filename or "template.html")

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
        current_user.id,
    )
    return template


@router.get("", response_model=list[TemplateResponse])
def list_templates(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[Template]:
    """List all available templates (shared across users)."""
    return db.query(Template).order_by(Template.created_at.desc()).all()


@router.post("/html", status_code=201, response_model=TemplateResponse)
def create_template_from_html(
    body: TemplateHtmlCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Template:
    """
    Save markup composed in the editor as a reusable template.

    The file-upload route stays for Maizzle-compiled output; this one exists
    because an editor holds a string, not a file.
    """
    html_bytes = body.html.encode("utf-8")
    _assert_within_size_limit(html_bytes)

    storage_key = _store(html_bytes, _slug(body.name))

    template = Template(
        name=body.name,
        storage_key=storage_key,
        original_filename=_slug(body.name),
        uploaded_by=str(current_user.id),
    )
    db.add(template)
    db.commit()
    db.refresh(template)

    logger.info(
        "Template created from editor. id=%s user=%s", template.id, current_user.id
    )
    return template


@router.get("/{template_id}/html", response_model=TemplateHtmlResponse)
def read_template_html(
    template_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TemplateHtmlResponse:
    """
    The stored markup, so the editor can open a template.

    Readable by any authenticated user, matching the list route — templates are
    a shared library. See docs/architecture.md decision 13.
    """
    template = db.get(Template, template_id)

    if not template:
        raise HTTPException(status_code=404, detail="Template not found.")

    try:
        return TemplateHtmlResponse(html=fetch_template(template.storage_key))
    except TemplateStorageError as exc:
        logger.exception("Failed to fetch template from storage. id=%s", template_id)
        raise HTTPException(
            status_code=502, detail="Failed to fetch template from storage."
        ) from exc


@router.put("/{template_id}/html", response_model=TemplateResponse)
def update_template_html(
    template_id: str,
    body: TemplateHtmlUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Template:
    """
    Replace a template's markup. Uploader only, mirroring delete.

    The new markup goes to a new key and the old object is deleted afterwards,
    rather than overwriting in place: a campaign created from the old version
    resolved its body at creation time, but anything still holding the old key
    should find what it expects until the swap has committed.
    """
    template = _get_own_template_or_404(template_id, db, current_user)

    html_bytes = body.html.encode("utf-8")
    _assert_within_size_limit(html_bytes)

    previous_key = template.storage_key
    template.storage_key = _store(html_bytes, template.original_filename)

    if body.name is not None:
        template.name = body.name

    db.commit()
    db.refresh(template)

    try:
        delete_template(previous_key)
    except TemplateStorageError:
        # The new version is already live. An orphaned object costs storage;
        # failing the request here would cost the user their edit.
        logger.exception(
            "R2 delete of superseded template object failed. key=%s", previous_key
        )

    logger.info("Template updated. id=%s user=%s", template_id, current_user.id)
    return template


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

    logger.info("Template deleted. id=%s user=%s", template_id, current_user.id)
