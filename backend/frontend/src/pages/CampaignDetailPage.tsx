import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import {
  useCampaign,
  useCampaignStats,
  useCcRecipients,
  useUpdateCampaign,
} from "@/api/hooks";
import { CampaignControls } from "@/components/CampaignControls";
import {
  CampaignForm,
  type CampaignFormValue,
} from "@/components/CampaignForm";
import { RecipientsTab, StatsRow } from "@/components/RecipientsTab";
import { PreviewPane } from "@/components/editor/PreviewPane";
import {
  Button,
  Card,
  Mono,
  Notice,
  PageHeading,
  Spinner,
  StatusBadge,
} from "@/components/ui/primitives";
import { can, isLive } from "@/lib/campaignState";

const TABS = ["Body", "Recipients", "Activity"] as const;
type Tab = (typeof TABS)[number];

export function CampaignDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("Body");
  const [draft, setDraft] = useState<CampaignFormValue | null>(null);

  const { data: campaign, isPending, error } = useCampaign(id);
  const { data: ccRecipients } = useCcRecipients(id);
  const update = useUpdateCampaign(id);

  // Poll while there is something to watch: validation draining, or a send in
  // progress. Settled numbers do not need re-fetching every three seconds.
  const { data: stats } = useCampaignStats(
    id,
    campaign ? isLive(campaign.status) || tab === "Recipients" : false,
  );

  // The CC list is a separate resource, and PATCH replaces it wholesale — so
  // saving before it has loaded would clear it. Wait for both.
  if (isPending || ccRecipients === undefined) {
    return <Spinner label="Loading campaign" />;
  }

  if (error || !campaign) {
    return (
      <Notice tone="danger" title="Could not load this campaign">
        {error instanceof ApiError ? error.detail : "Unknown error."}
      </Notice>
    );
  }

  const editable = can("edit", campaign.status);
  const value: CampaignFormValue = draft ?? {
    name: campaign.name,
    subject: campaign.subject,
    templateBody: campaign.template_body,
    fromAddress: campaign.from_address ?? "",
    ccEmails: ccRecipients.map((cc) => cc.email),
  };

  return (
    <>
      <PageHeading
        title={campaign.name}
        subtitle={campaign.subject}
        actions={
          <>
            <StatusBadge status={campaign.status} />
            <Button onClick={() => void navigate("/")}>Back</Button>
          </>
        }
      />

      <div className="mb-6">
        <Card>
          <CampaignControls campaign={campaign} stats={stats} />
        </Card>
      </div>

      <div className="mb-6 flex gap-2">
        {TABS.map((name) => (
          <Button
            key={name}
            variant={tab === name ? "primary" : "secondary"}
            onClick={() => setTab(name)}
          >
            {name}
          </Button>
        ))}
      </div>

      {tab === "Body" ? (
        editable ? (
          <div className="flex flex-col gap-6">
            <CampaignForm
              key={`cc:${ccRecipients.length}`}
              value={value}
              onChange={setDraft}
            />
            <div className="flex items-center gap-3">
              <Button
                variant="primary"
                disabled={draft === null || update.isPending}
                onClick={() =>
                  update.mutate(
                    {
                      name: value.name,
                      subject: value.subject,
                      template_body: value.templateBody,
                      from_address: value.fromAddress || null,
                      cc_emails: value.ccEmails,
                    },
                    { onSuccess: () => setDraft(null) },
                  )
                }
              >
                {update.isPending ? "Saving…" : "Save changes"}
              </Button>
              {draft !== null ? (
                <span className="text-caption text-muted">Unsaved changes.</span>
              ) : null}
              {update.error ? (
                <span className="text-caption text-danger">
                  {update.error instanceof ApiError
                    ? update.error.detail
                    : update.error.message}
                </span>
              ) : null}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <Notice tone="info" title="Read only">
              Only drafts can be edited. This campaign is {campaign.status}.
            </Notice>
            <PreviewPane html={campaign.template_body} />
          </div>
        )
      ) : null}

      {tab === "Recipients" ? (
        <RecipientsTab campaignId={id} stats={stats} editable={editable} />
      ) : null}

      {tab === "Activity" ? (
        <div className="flex flex-col gap-6">
          {stats ? <StatsRow stats={stats} /> : <Spinner label="Loading stats" />}

          <Card>
            <dl className="grid gap-3 text-small md:grid-cols-2">
              <Detail label="Campaign id" value={<Mono>{campaign.id}</Mono>} />
              <Detail
                label="Sending from"
                value={<Mono>{campaign.from_address ?? "your own mailbox"}</Mono>}
              />
              <Detail
                label="Scheduled for"
                value={
                  campaign.scheduled_at
                    ? new Date(campaign.scheduled_at).toLocaleString()
                    : "—"
                }
              />
              <Detail
                label="Last updated"
                value={new Date(campaign.updated_at).toLocaleString()}
              />
            </dl>
          </Card>

          {isLive(campaign.status) ? (
            <p className="text-caption text-muted">
              Updating every few seconds while the campaign is running.
            </p>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="font-mono text-label uppercase tracking-wide text-muted">
        {label}
      </dt>
      <dd className="mt-0.5">{value}</dd>
    </div>
  );
}
