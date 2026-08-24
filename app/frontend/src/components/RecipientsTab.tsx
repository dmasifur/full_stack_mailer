/**
 * Recipients: upload, validation, and the send gate.
 *
 * The sharpest edge in the whole API is here. The send worker only picks up
 * recipients that are `pending` AND `dns_valid`, so a campaign started while
 * rows are still at `pending_validation` finds nothing to do and transitions
 * itself to `completed` — which is terminal — having sent nothing. The API
 * refuses that with a 409; this screen makes sure the user never gets there,
 * by keeping the send controls disabled until validation has drained.
 */

import { useRef, useState } from "react";

import { ApiError } from "@/api/client";
import { useRecipients, useUploadRecipients } from "@/api/hooks";
import type { CampaignStats } from "@/api/types";
import {
  Button,
  Card,
  EmptyState,
  Mono,
  Notice,
  Spinner,
  StatusBadge,
} from "./ui/primitives";

const FILTERS = [
  { value: null, label: "All" },
  { value: "sent", label: "Sent" },
  { value: "failed", label: "Failed" },
  { value: "invalid", label: "Invalid" },
  { value: "pending", label: "Pending" },
] as const;

export function RecipientsTab({
  campaignId,
  stats,
  editable,
}: {
  campaignId: string;
  stats: CampaignStats | undefined;
  editable: boolean;
}) {
  const [filter, setFilter] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const fileInput = useRef<HTMLInputElement>(null);

  const upload = useUploadRecipients(campaignId);
  const { data, isPending } = useRecipients(campaignId, page, filter);

  const validating = (stats?.awaiting_validation ?? 0) > 0;

  return (
    <div className="flex flex-col gap-6">
      {editable ? (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <p className="font-medium">Upload recipients</p>
              <p className="mt-1 text-small text-muted">
                CSV with an <Mono>email</Mono> column. <Mono>first_name</Mono>{" "}
                and <Mono>last_name</Mono> are optional and feed merge tags.
                Re-uploading the same file will not duplicate rows.
              </p>
            </div>
            <input
              ref={fileInput}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) upload.mutate(file);
                event.target.value = "";
              }}
            />
            <Button
              variant="primary"
              disabled={upload.isPending}
              onClick={() => fileInput.current?.click()}
            >
              {upload.isPending ? "Uploading…" : "Choose CSV"}
            </Button>
          </div>

          {upload.data ? (
            <div className="mt-4">
              <Notice tone="success" title="Import finished">
                {upload.data.summary.imported} imported,{" "}
                {upload.data.summary.invalid} rejected, out of{" "}
                {upload.data.summary.total_rows} rows.
              </Notice>
            </div>
          ) : null}

          {upload.error ? (
            <div className="mt-4">
              <Notice tone="danger" title="Upload failed">
                {upload.error instanceof ApiError
                  ? upload.error.detail
                  : upload.error.message}
              </Notice>
            </div>
          ) : null}
        </Card>
      ) : null}

      {validating ? (
        <Notice tone="warn" title="Validating domains">
          Checking MX records for {stats?.awaiting_validation} address
          {stats?.awaiting_validation === 1 ? "" : "es"}. Sending stays disabled
          until this finishes — a campaign started now would send to nobody and
          mark itself complete.
        </Notice>
      ) : null}

      {stats ? <StatsRow stats={stats} /> : null}

      <div>
        <div className="mb-3 flex flex-wrap gap-2">
          {FILTERS.map((option) => (
            <Button
              key={option.label}
              variant={filter === option.value ? "primary" : "secondary"}
              onClick={() => {
                setFilter(option.value);
                setPage(1);
              }}
            >
              {option.label}
            </Button>
          ))}
        </div>

        {isPending ? <Spinner label="Loading recipients" /> : null}

        {data && data.items.length === 0 ? (
          <EmptyState
            message={
              filter
                ? `No recipients with status "${filter}".`
                : "No recipients yet. Upload a CSV to add them."
            }
          />
        ) : null}

        {data && data.items.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-small">
              <thead className="border-b border-border bg-surface/40 text-left">
                <tr>
                  <th className="px-4 py-2 font-medium">Email</th>
                  <th className="px-4 py-2 font-medium">Name</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((recipient) => (
                  <tr key={recipient.id} className="border-b border-border last:border-0">
                    <td className="px-4 py-2">
                      <Mono>{recipient.email}</Mono>
                    </td>
                    <td className="px-4 py-2 text-muted">
                      {[recipient.first_name, recipient.last_name]
                        .filter(Boolean)
                        .join(" ") || "—"}
                    </td>
                    <td className="px-4 py-2">
                      <StatusBadge status={recipient.status} />
                    </td>
                    <td className="px-4 py-2 text-muted">
                      {recipient.failure_reason ? (
                        <Mono>{recipient.failure_reason}</Mono>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}

        {data && data.total > data.page_size ? (
          <div className="mt-4 flex items-center justify-center gap-3">
            <Button disabled={page <= 1} onClick={() => setPage((n) => n - 1)}>
              Previous
            </Button>
            <span className="font-mono text-label text-muted">
              {page} / {Math.ceil(data.total / data.page_size)}
            </span>
            <Button
              disabled={page >= Math.ceil(data.total / data.page_size)}
              onClick={() => setPage((n) => n + 1)}
            >
              Next
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function StatsRow({ stats }: { stats: CampaignStats }) {
  const tiles = [
    { label: "Total", value: stats.total_recipients, tone: "" },
    { label: "Sent", value: stats.sent, tone: "text-success" },
    { label: "Failed", value: stats.failed, tone: "text-danger" },
    { label: "Pending", value: stats.pending, tone: "" },
    { label: "Validating", value: stats.awaiting_validation, tone: "" },
    { label: "Invalid", value: stats.invalid, tone: "text-warn" },
  ];

  return (
    <div className="grid grid-cols-3 gap-3 md:grid-cols-6">
      {tiles.map((tile) => (
        <div
          key={tile.label}
          className="rounded-lg border border-border bg-surface/40 px-4 py-3"
        >
          <p className="font-mono text-label uppercase tracking-wide text-muted">
            {tile.label}
          </p>
          <p className={`mt-1 font-heading text-h4 font-bold ${tile.tone}`}>
            {tile.value}
          </p>
        </div>
      ))}
    </div>
  );
}
