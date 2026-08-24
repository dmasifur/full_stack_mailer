import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { useCampaigns } from "@/api/hooks";
import {
  Button,
  Card,
  EmptyState,
  Notice,
  PageHeading,
  Spinner,
  StatusBadge,
} from "@/components/ui/primitives";

const PAGE_SIZE = 20;

export function CampaignListPage() {
  const [page, setPage] = useState(1);
  const navigate = useNavigate();
  const { data, isPending, error } = useCampaigns(page);

  const lastPage = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;

  return (
    <>
      <PageHeading
        title="Campaigns"
        subtitle={data ? `${data.total} total` : undefined}
        actions={
          <Button variant="primary" onClick={() => void navigate("/campaigns/new")}>
            New campaign
          </Button>
        }
      />

      {isPending ? <Spinner label="Loading campaigns" /> : null}

      {error ? (
        <Notice tone="danger" title="Could not load campaigns">
          {error.message}
        </Notice>
      ) : null}

      {data && data.items.length === 0 ? (
        <EmptyState
          message="No campaigns yet."
          action={
            <Button variant="primary" onClick={() => void navigate("/campaigns/new")}>
              Create the first one
            </Button>
          }
        />
      ) : null}

      {data && data.items.length > 0 ? (
        <div className="flex flex-col gap-2">
          {data.items.map((campaign) => (
            <Link key={campaign.id} to={`/campaigns/${campaign.id}`}>
              <Card className="transition-colors hover:border-accent">
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{campaign.name}</p>
                    <p className="mt-0.5 truncate text-small text-muted">
                      {campaign.subject}
                    </p>
                  </div>
                  <div className="flex shrink-0 items-center gap-4">
                    {campaign.scheduled_at ? (
                      <span className="font-mono text-label text-muted">
                        {new Date(campaign.scheduled_at).toLocaleString()}
                      </span>
                    ) : null}
                    <StatusBadge status={campaign.status} />
                  </div>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      ) : null}

      {lastPage > 1 ? (
        <div className="mt-6 flex items-center justify-center gap-3">
          <Button disabled={page <= 1} onClick={() => setPage((n) => n - 1)}>
            Previous
          </Button>
          <span className="font-mono text-label text-muted">
            {page} / {lastPage}
          </span>
          <Button disabled={page >= lastPage} onClick={() => setPage((n) => n + 1)}>
            Next
          </Button>
        </div>
      ) : null}
    </>
  );
}
