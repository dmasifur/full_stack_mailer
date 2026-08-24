import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { useCreateCampaign, useTemplateHtml, useTemplates } from "@/api/hooks";
import {
  CampaignForm,
  type CampaignFormValue,
} from "@/components/CampaignForm";
import {
  Button,
  Card,
  Field,
  Notice,
  PageHeading,
  inputClass,
} from "@/components/ui/primitives";

const EMPTY: CampaignFormValue = {
  name: "",
  subject: "",
  templateBody: "",
  fromAddress: "",
  ccEmails: [],
};

export function NewCampaignPage() {
  const navigate = useNavigate();
  const [value, setValue] = useState<CampaignFormValue>(EMPTY);
  const [templateId, setTemplateId] = useState<string | null>(null);

  const { data: templates } = useTemplates();
  const { data: templateHtml } = useTemplateHtml(templateId);
  const create = useCreateCampaign();

  // Applying a template replaces the body once, when the markup arrives —
  // not on every render, which would discard everything typed afterwards.
  useEffect(() => {
    if (templateHtml) {
      setValue((current) => ({ ...current, templateBody: templateHtml.html }));
    }
  }, [templateHtml]);

  // The editor keeps its own state once mounted, so seeding it means
  // remounting. The key changes when the markup lands, not merely when a
  // template is picked.
  const formKey =
    templateId === null
      ? "blank"
      : templateHtml
        ? `template:${templateId}`
        : `loading:${templateId}`;

  const incomplete =
    value.name.trim() === "" ||
    value.subject.trim() === "" ||
    value.templateBody.trim() === "";

  function submit() {
    create.mutate(
      {
        name: value.name,
        subject: value.subject,
        template_body: value.templateBody,
        from_address: value.fromAddress || null,
        cc_emails: value.ccEmails,
      },
      { onSuccess: (campaign) => void navigate(`/campaigns/${campaign.id}`) },
    );
  }

  return (
    <>
      <PageHeading
        title="New campaign"
        subtitle="Saved as a draft. Nothing sends until you add recipients and start it."
        actions={
          <>
            <Button onClick={() => void navigate("/")}>Cancel</Button>
            <Button
              variant="primary"
              disabled={incomplete || create.isPending}
              onClick={submit}
            >
              {create.isPending ? "Saving…" : "Save draft"}
            </Button>
          </>
        }
      />

      {create.error ? (
        <div className="mb-6">
          <Notice tone="danger" title="Could not create the campaign">
            {create.error instanceof ApiError
              ? create.error.detail
              : create.error.message}
          </Notice>
        </div>
      ) : null}

      {templates && templates.length > 0 ? (
        <div className="mb-6">
          <Card>
            <Field
              label="Start from a template"
              hint="Optional. Loads the template's markup into the editor; the campaign keeps its own copy."
            >
              <select
                className={inputClass}
                value={templateId ?? ""}
                onChange={(event) =>
                  setTemplateId(event.target.value || null)
                }
              >
                <option value="">Blank</option>
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name}
                  </option>
                ))}
              </select>
            </Field>
          </Card>
        </div>
      ) : null}

      <CampaignForm key={formKey} value={value} onChange={setValue} />
    </>
  );
}
