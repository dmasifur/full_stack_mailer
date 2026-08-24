import { useState } from "react";

import { ApiError } from "@/api/client";
import {
  useCreateSenderAddress,
  useDeleteSenderAddress,
  useSenderAddresses,
  useUpdateSenderAddress,
} from "@/api/hooks";
import {
  Button,
  Card,
  EmptyState,
  Field,
  Mono,
  Notice,
  PageHeading,
  Spinner,
  inputClass,
} from "@/components/ui/primitives";

export function SettingsPage() {
  const { data: addresses, isPending } = useSenderAddresses();
  const create = useCreateSenderAddress();
  const update = useUpdateSenderAddress();
  const remove = useDeleteSenderAddress();

  const [label, setLabel] = useState("");
  const [email, setEmail] = useState("");

  return (
    <>
      <PageHeading
        title="Sender addresses"
        subtitle="Shared mailboxes you can send campaigns from. Your own mailbox always works without registering it."
      />

      <div className="mb-8">
        <Card>
          <div className="grid items-end gap-4 md:grid-cols-[1fr_1fr_auto]">
            <Field label="Label" hint="How it appears in the campaign form.">
              <input
                className={inputClass}
                value={label}
                maxLength={255}
                onChange={(event) => setLabel(event.target.value)}
                placeholder="Support inbox"
              />
            </Field>
            <Field
              label="Address"
              hint="You need send rights on this mailbox in Microsoft 365."
            >
              <input
                className={inputClass}
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="support@example.com"
              />
            </Field>
            <Button
              variant="primary"
              disabled={label.trim() === "" || email.trim() === "" || create.isPending}
              onClick={() =>
                create.mutate(
                  { label, email, is_default: (addresses ?? []).length === 0 },
                  {
                    onSuccess: () => {
                      setLabel("");
                      setEmail("");
                    },
                  },
                )
              }
            >
              Add
            </Button>
          </div>

          {create.error ? (
            <div className="mt-4">
              <Notice tone="danger">
                {create.error instanceof ApiError
                  ? create.error.detail
                  : create.error.message}
              </Notice>
            </div>
          ) : null}
        </Card>
      </div>

      {isPending ? <Spinner label="Loading addresses" /> : null}

      {addresses && addresses.length === 0 ? (
        <EmptyState message="No shared addresses registered. Campaigns will send from your own mailbox." />
      ) : null}

      <div className="flex flex-col gap-2">
        {(addresses ?? []).map((address) => (
          <Card key={address.id}>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="min-w-0">
                <p className="truncate font-medium">
                  {address.label}
                  {address.is_default ? (
                    <span className="ml-2 font-mono text-label uppercase text-accent">
                      default
                    </span>
                  ) : null}
                </p>
                <p className="mt-0.5 truncate text-small text-muted">
                  <Mono>{address.email}</Mono>
                </p>
              </div>

              <div className="flex shrink-0 gap-2">
                {!address.is_default ? (
                  <Button
                    disabled={update.isPending}
                    onClick={() =>
                      update.mutate({ id: address.id, is_default: true })
                    }
                  >
                    Make default
                  </Button>
                ) : null}
                <Button
                  variant="danger"
                  disabled={remove.isPending}
                  onClick={() => {
                    if (window.confirm(`Remove ${address.email}?`)) {
                      remove.mutate(address.id);
                    }
                  }}
                >
                  Remove
                </Button>
              </div>
            </div>
          </Card>
        ))}
      </div>

      {remove.error ? (
        <div className="mt-4">
          <Notice tone="danger">
            {remove.error instanceof ApiError
              ? remove.error.detail
              : remove.error.message}
          </Notice>
        </div>
      ) : null}
    </>
  );
}
