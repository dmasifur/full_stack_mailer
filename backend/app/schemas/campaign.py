from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, EmailStr, Field, field_validator


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


class CampaignSchedule(BaseModel):
    """
    When to send a campaign.

    AwareDatetime, not datetime: Celery is configured with enable_utc=True, so a
    naive value is silently reinterpreted as UTC and fires at the wrong moment
    for anyone not already in UTC.
    """

    scheduled_at: AwareDatetime

    @field_validator("scheduled_at")
    @classmethod
    def _must_be_future(cls, v: datetime) -> datetime:
        if v <= datetime.now(tz=UTC):
            raise ValueError(
                "scheduled_at must be in the future. To send now, use /start."
            )
        return v


class RecipientResponse(BaseModel):
    id: UUID
    email: str
    first_name: str | None
    last_name: str | None
    status: str
    dns_valid: bool | None
    retry_count: int
    failure_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class RecipientListResponse(BaseModel):
    items: list[RecipientResponse]
    total: int
    page: int
    page_size: int


class CampaignStatsResponse(BaseModel):
    """Recipient counts per status, so an under-sending campaign can be explained."""

    campaign_id: UUID
    status: str
    total_recipients: int
    by_status: dict[str, int]
    sent: int
    failed: int
    pending: int
    awaiting_validation: int
    invalid: int


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
