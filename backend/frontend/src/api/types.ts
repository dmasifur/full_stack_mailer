/**
 * Response shapes, mirroring backend/app/schemas/.
 *
 * `npm run gen:api` regenerates a full schema from the live OpenAPI document;
 * these are the hand-kept subset the UI actually reads, so a field rename
 * shows up as a type error here rather than as undefined at runtime.
 */

import type { CampaignStatus } from "@/lib/campaignState";

export interface User {
  readonly id: string;
  readonly email: string;
  readonly full_name: string | null;
  readonly created_at: string;
}

export interface Campaign {
  readonly id: string;
  readonly user_id: string;
  readonly name: string;
  readonly subject: string;
  readonly template_body: string;
  readonly template_id: string | null;
  readonly from_address: string | null;
  readonly status: CampaignStatus;
  readonly scheduled_at: string | null;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface Page<T> {
  readonly items: readonly T[];
  readonly total: number;
  readonly page: number;
  readonly page_size: number;
}

export type RecipientStatus =
  | "pending_validation"
  | "pending"
  | "sending"
  | "sent"
  | "failed"
  | "invalid";

export interface Recipient {
  readonly id: string;
  readonly email: string;
  readonly first_name: string | null;
  readonly last_name: string | null;
  readonly status: RecipientStatus;
  readonly dns_valid: boolean | null;
  readonly retry_count: number;
  readonly failure_reason: string | null;
  readonly created_at: string;
}

export interface CampaignStats {
  readonly campaign_id: string;
  readonly status: CampaignStatus;
  readonly total_recipients: number;
  readonly by_status: Readonly<Record<string, number>>;
  readonly sent: number;
  readonly failed: number;
  readonly pending: number;
  readonly awaiting_validation: number;
  readonly invalid: number;
}

export interface ImportSummary {
  readonly total_rows: number;
  readonly imported: number;
  readonly invalid: number;
}

export interface RecipientUploadResult {
  readonly message: string;
  readonly summary: ImportSummary;
}

export interface Template {
  readonly id: string;
  readonly name: string;
  readonly original_filename: string;
  readonly uploaded_by: string;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface SenderAddress {
  readonly id: string;
  readonly label: string;
  readonly email: string;
  readonly is_default: boolean;
  readonly created_at: string;
}

export interface CcRecipient {
  readonly id: string;
  readonly email: string;
  readonly created_at: string;
}
