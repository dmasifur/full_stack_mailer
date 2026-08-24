/**
 * The fields a campaign carries, shared by create and edit.
 *
 * The body editor owns its own modes; this only holds the value it produces.
 */

import { useState } from "react";

import { useSenderAddresses } from "@/api/hooks";
import { splitEmails } from "@/lib/emails";
import { CampaignBodyEditor } from "./editor/CampaignBodyEditor";
import { Card, Field, Notice, inputClass } from "./ui/primitives";

/** Matches CampaignCreate.cc_emails in backend/app/schemas/campaign.py. */
const MAX_CC = 20;

export interface CampaignFormValue {
  name: string;
  subject: string;
  templateBody: string;
  fromAddress: string;
  ccEmails: string[];
}

export function CampaignForm({
  value,
  onChange,
  disabled = false,
}: {
  value: CampaignFormValue;
  onChange: (next: CampaignFormValue) => void;
  disabled?: boolean;
}) {
  const { data: senders } = useSenderAddresses();
  const [ccRaw, setCcRaw] = useState(value.ccEmails.join(", "));

  const set = <K extends keyof CampaignFormValue>(
    key: K,
    next: CampaignFormValue[K],
  ) => onChange({ ...value, [key]: next });

  const ccCount = splitEmails(ccRaw).length;

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <div className="grid gap-5 md:grid-cols-2">
          <Field label="Campaign name" hint="Internal only — recipients never see it.">
            <input
              className={inputClass}
              value={value.name}
              disabled={disabled}
              maxLength={255}
              onChange={(event) => set("name", event.target.value)}
              placeholder="September newsletter"
            />
          </Field>

          <Field label="Subject" hint="What lands in the inbox.">
            <input
              className={inputClass}
              value={value.subject}
              disabled={disabled}
              maxLength={500}
              onChange={(event) => set("subject", event.target.value)}
              placeholder="Product update"
            />
          </Field>

          <Field
            label="Send from"
            hint="Leave as your own mailbox unless you hold send rights on a shared one."
          >
            <select
              className={inputClass}
              value={value.fromAddress}
              disabled={disabled}
              onChange={(event) => set("fromAddress", event.target.value)}
            >
              <option value="">My own mailbox</option>
              {(senders ?? []).map((sender) => (
                <option key={sender.id} value={sender.email}>
                  {sender.label} — {sender.email}
                </option>
              ))}
            </select>
          </Field>

          <Field label="CC" hint={`Comma separated. ${ccCount}/${MAX_CC} used.`}>
            <input
              className={inputClass}
              value={ccRaw}
              disabled={disabled}
              onChange={(event) => {
                setCcRaw(event.target.value);
                set("ccEmails", splitEmails(event.target.value));
              }}
              placeholder="team@example.com, archive@example.com"
            />
          </Field>
        </div>

        {ccCount > MAX_CC ? (
          <div className="mt-4">
            <Notice tone="danger">
              At most {MAX_CC} CC addresses. Remove {ccCount - MAX_CC}.
            </Notice>
          </div>
        ) : null}
      </Card>

      <CampaignBodyEditor
        value={value.templateBody}
        subject={value.subject}
        onChange={(html) => set("templateBody", html)}
      />
    </div>
  );
}
