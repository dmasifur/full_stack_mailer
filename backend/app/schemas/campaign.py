from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CampaignCreate(BaseModel):
    name: str = Field(..., max_length=255)
    subject: str = Field(..., max_length=500)
    template_body: str = Field(..., min_length=1)


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=500)
    template_body: str | None = Field(default=None, min_length=1)


class CampaignResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    subject: str
    template_body: str
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
