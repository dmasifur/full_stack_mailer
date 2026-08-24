/**
 * Start, schedule, pause, resume, retry, delete.
 *
 * Buttons are gated on the state machine mirrored in lib/campaignState.ts and
 * on whether the campaign can actually send, so the user is not offered an
 * action the API will refuse. The API stays the authority — this only avoids
 * making a 409 the way people discover the rules.
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import {
  useCampaignAction,
  useDeleteCampaign,
  useScheduleCampaign,
} from "@/api/hooks";
import type { Campaign, CampaignStats } from "@/api/types";
import { blockedReason, can } from "@/lib/campaignState";
import { Button, Notice, inputClass } from "./ui/primitives";

export function CampaignControls({
  campaign,
  stats,
}: {
  campaign: Campaign;
  stats: CampaignStats | undefined;
}) {
  const navigate = useNavigate();
  const [scheduling, setScheduling] = useState(false);
  const [scheduledAt, setScheduledAt] = useState("");

  const action = useCampaignAction(campaign.id);
  const schedule = useScheduleCampaign(campaign.id);
  const remove = useDeleteCampaign();

  const { status } = campaign;

  // Mirrors _assert_sendable in server/api/campaigns.py.
  const noRecipients = (stats?.total_recipients ?? 0) === 0;
  const validating = (stats?.awaiting_validation ?? 0) > 0;
  const sendable = !noRecipients && !validating;

  const sendBlock = noRecipients
    ? "Add recipients before sending."
    : validating
      ? "Waiting for domain validation to finish."
      : null;

  const error = action.error ?? schedule.error ?? remove.error;
  const busy = action.isPending || schedule.isPending || remove.isPending;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Action
          label="Start sending"
          variant="primary"
          available={can("start", status) && sendable}
          reason={sendBlock ?? blockedReason("start", status)}
          busy={busy}
          onClick={() => action.mutate("start")}
        />
        <Action
          label="Schedule"
          available={can("schedule", status) && sendable}
          reason={sendBlock ?? blockedReason("schedule", status)}
          busy={busy}
          onClick={() => setScheduling((on) => !on)}
        />
        <Action
          label="Pause"
          available={can("pause", status)}
          reason={blockedReason("pause", status)}
          busy={busy}
          onClick={() => action.mutate("pause")}
        />
        <Action
          label="Resume"
          available={can("resume", status)}
          reason={blockedReason("resume", status)}
          busy={busy}
          onClick={() => action.mutate("resume")}
        />
        <Action
          label="Retry"
          available={can("retry", status)}
          reason={blockedReason("retry", status)}
          busy={busy}
          onClick={() => action.mutate("retry")}
        />

        <div className="ml-auto">
          <Action
            label="Delete"
            variant="danger"
            available={can("delete", status)}
            reason={blockedReason("delete", status)}
            busy={busy}
            onClick={() => {
              if (
                window.confirm(
                  `Delete "${campaign.name}"? Recipients, CC list, and logs go with it.`,
                )
              ) {
                remove.mutate(campaign.id, {
                  onSuccess: () => void navigate("/"),
                });
              }
            }}
          />
        </div>
      </div>

      {scheduling ? (
        <div className="flex flex-wrap items-end gap-3 rounded-lg border border-border bg-surface/40 p-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-small font-medium">Send at</span>
            <input
              type="datetime-local"
              className={inputClass}
              value={scheduledAt}
              onChange={(event) => setScheduledAt(event.target.value)}
            />
          </label>
          <Button
            variant="primary"
            disabled={scheduledAt === "" || schedule.isPending}
            onClick={() => {
              // The API requires an offset-aware, future timestamp; the input
              // gives local wall-clock time, so the offset is added here.
              const iso = new Date(scheduledAt).toISOString();
              schedule.mutate(iso, { onSuccess: () => setScheduling(false) });
            }}
          >
            Confirm schedule
          </Button>
          <span className="text-caption text-muted">
            Your local time. Must be in the future.
          </span>
        </div>
      ) : null}

      {error ? <ActionError error={error} /> : null}
    </div>
  );
}

function Action({
  label,
  variant = "secondary",
  available,
  reason,
  busy,
  onClick,
}: {
  label: string;
  variant?: "primary" | "secondary" | "danger";
  available: boolean;
  reason: string | null;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      variant={variant}
      disabled={!available || busy}
      onClick={onClick}
      {...(!available && reason ? { title: reason } : {})}
    >
      {label}
    </Button>
  );
}

function ActionError({ error }: { error: Error }) {
  // 503 is not a failure to fix: the broker was unreachable and the API
  // deliberately left the campaign untouched, so the same click will work
  // once it is back. Saying so beats a generic error.
  if (error instanceof ApiError && error.isBrokerUnavailable) {
    return (
      <Notice tone="warn" title="Task queue unreachable">
        The campaign was left unchanged. Try again in a moment.
      </Notice>
    );
  }

  if (error instanceof ApiError && error.isConflict) {
    return (
      <Notice tone="warn" title="Not allowed right now">
        {error.detail}
      </Notice>
    );
  }

  return (
    <Notice tone="danger" title="That did not work">
      {error instanceof ApiError ? error.detail : error.message}
    </Notice>
  );
}
