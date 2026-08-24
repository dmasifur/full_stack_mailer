/**
 * A mirror of the backend's campaign state machine.
 *
 * Kept in step with `server/services/campaign_state.py` — change one and
 * change the other. The API remains the authority; this exists so the UI can
 * disable an action that would be refused, rather than letting the user find
 * out through a 409.
 */

export const CAMPAIGN_STATUSES = [
  "draft",
  "scheduled",
  "running",
  "paused",
  "completed",
  "failed",
] as const;

export type CampaignStatus = (typeof CAMPAIGN_STATUSES)[number];

export const VALID_TRANSITIONS: Record<CampaignStatus, readonly CampaignStatus[]> = {
  draft: ["scheduled", "running"],
  scheduled: ["running", "draft"],
  running: ["paused", "completed", "failed"],
  paused: ["running", "scheduled", "failed"],
  completed: [], // terminal, by design — see docs/architecture.md §3
  failed: ["running"],
};

export type CampaignAction =
  | "start"
  | "schedule"
  | "pause"
  | "resume"
  | "retry"
  | "edit"
  | "delete";

/**
 * Which statuses each action is offered from.
 *
 * Not derived from VALID_TRANSITIONS: several actions land on the same status
 * from different places (`resume` and `retry` both reach `running`), and two
 * are governed by rules outside the state machine — drafts alone are editable,
 * and delete is blocked while a campaign is live.
 */
const ALLOWED_FROM: Record<CampaignAction, readonly CampaignStatus[]> = {
  start: ["draft"],
  schedule: ["draft", "paused"],
  pause: ["running"],
  resume: ["paused"],
  retry: ["failed"],
  edit: ["draft"],
  delete: ["draft", "paused", "completed", "failed"],
};

export function can(action: CampaignAction, status: CampaignStatus): boolean {
  return ALLOWED_FROM[action].includes(status);
}

/** Whether the campaign is doing something right now, and worth polling. */
export function isLive(status: CampaignStatus): boolean {
  return status === "running";
}

export function isTerminal(status: CampaignStatus): boolean {
  return VALID_TRANSITIONS[status].length === 0;
}

/**
 * Why an action is unavailable, in the user's terms.
 *
 * Returns null when the action is available. Copy is direct and says what
 * would make it possible, per the brand voice.
 */
export function blockedReason(
  action: CampaignAction,
  status: CampaignStatus,
): string | null {
  if (can(action, status)) return null;

  if (status === "completed") {
    return "This campaign has finished. Completed is a final state.";
  }
  if (status === "running" && action !== "pause") {
    return "This campaign is sending. Pause it first.";
  }
  if (action === "edit") {
    return "Only drafts can be edited.";
  }
  return `Not available while the campaign is ${status}.`;
}
