from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class CampaignCreate(BaseModel):
    name: str = Field(..., max_length=255)
    subject: str = Field(..., max_length=500)
    template_body: str = Field(..., min_length=1)
    template_id: UUID | None = None
    from_address: EmailStr | None = None
    cc_emails: list[EmailStr] = Field(default_factory=list, max_length=20)


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=500)
    template_body: str | None = Field(default=None, min_length=1)
    from_address: EmailStr | None = None
    cc_emails: list[EmailStr] | None = None


class CampaignResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    subject: str
    template_body: str
    template_id: UUID | None
    from_address: str | None
    status: str
    scheduled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CampaignListResponse(BaseModel):
    items: list[CampaignResponse]
    total: int
    page: int
    page_size: int


class ImportSummarySchema(BaseModel):
    total_rows: int
    imported: int
    invalid: int


class RecipientUploadResponse(BaseModel):
    message: str
    summary: ImportSummarySchema


class TemplateResponse(BaseModel):
    id: UUID
    name: str
    original_filename: str
    uploaded_by: UUID
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SenderAddressCreate(BaseModel):
    label: str = Field(..., max_length=255)
    email: EmailStr
    is_default: bool = False


class SenderAddressUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=255)
    is_default: bool | None = None


class SenderAddressResponse(BaseModel):
    id: UUID
    label: str
    email: str
    is_default: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class CcRecipientAdd(BaseModel):
    emails: list[EmailStr] = Field(..., min_length=1, max_length=20)


class CcRecipientResponse(BaseModel):
    id: UUID
    email: str
    created_at: datetime

    model_config = {"from_attributes": True}
