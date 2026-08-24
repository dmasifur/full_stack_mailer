import { useState } from "react";

import { ApiError } from "@/api/client";
import {
  useCurrentUser,
  useDeleteTemplate,
  useSaveTemplate,
  useTemplateHtml,
  useTemplates,
  useUpdateTemplate,
} from "@/api/hooks";
import { CampaignBodyEditor } from "@/components/editor/CampaignBodyEditor";
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

type Editing = { kind: "new" } | { kind: "existing"; id: string } | null;

export function TemplatesPage() {
  const { data: user } = useCurrentUser();
  const { data: templates, isPending } = useTemplates();
  // Not `string | "new"`: that union collapses to string and the compiler
  // stops telling "creating" apart from "editing this id".
  const [editing, setEditing] = useState<Editing>(null);

  return (
    <>
      <PageHeading
        title="Templates"
        subtitle="Shared across everyone using this service. Only the uploader can change or delete one."
        actions={
          <Button variant="primary" onClick={() => setEditing({ kind: "new" })}>
            New template
          </Button>
        }
      />

      {editing !== null ? (
        <div className="mb-8">
          <TemplateEditor
            templateId={editing.kind === "existing" ? editing.id : null}
            onDone={() => setEditing(null)}
          />
        </div>
      ) : null}

      {isPending ? <Spinner label="Loading templates" /> : null}

      {templates && templates.length === 0 ? (
        <EmptyState
          message="No templates yet. Save one to reuse its markup across campaigns."
          action={
            <Button variant="primary" onClick={() => setEditing({ kind: "new" })}>
              Create one
            </Button>
          }
        />
      ) : null}

      <div className="flex flex-col gap-2">
        {(templates ?? []).map((template) => (
          <TemplateRow
            key={template.id}
            template={template}
            isOwner={user?.id === template.uploaded_by}
            onEdit={() => setEditing({ kind: "existing", id: template.id })}
          />
        ))}
      </div>
    </>
  );
}

function TemplateRow({
  template,
  isOwner,
  onEdit,
}: {
  template: { id: string; name: string; original_filename: string; created_at: string };
  isOwner: boolean;
  onEdit: () => void;
}) {
  const remove = useDeleteTemplate();

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="truncate font-medium">{template.name}</p>
          <p className="mt-0.5 text-small text-muted">
            <Mono>{template.original_filename}</Mono> ·{" "}
            {new Date(template.created_at).toLocaleDateString()}
          </p>
        </div>

        {/* Non-owners get no controls at all: the API refuses, and offering a
            button that always fails is worse than not offering one. */}
        {isOwner ? (
          <div className="flex shrink-0 gap-2">
            <Button onClick={onEdit}>Edit</Button>
            <Button
              variant="danger"
              disabled={remove.isPending}
              onClick={() => {
                if (window.confirm(`Delete "${template.name}"?`)) {
                  remove.mutate(template.id);
                }
              }}
            >
              Delete
            </Button>
          </div>
        ) : (
          <span className="shrink-0 text-caption text-muted">
            Uploaded by someone else
          </span>
        )}
      </div>

      {remove.error ? (
        <div className="mt-3">
          <Notice tone="danger">
            {remove.error instanceof ApiError
              ? remove.error.detail
              : remove.error.message}
          </Notice>
        </div>
      ) : null}
    </Card>
  );
}

function TemplateEditor({
  templateId,
  onDone,
}: {
  templateId: string | null;
  onDone: () => void;
}) {
  const { data: existing, isPending } = useTemplateHtml(templateId);
  const { data: templates } = useTemplates();
  const save = useSaveTemplate();
  const update = useUpdateTemplate();

  const current = templates?.find((template) => template.id === templateId);
  const [name, setName] = useState(current?.name ?? "");
  const [html, setHtml] = useState("");

  if (templateId !== null && isPending) {
    return <Spinner label="Loading template" />;
  }

  const body = html || existing?.html || "";
  const error = save.error ?? update.error;

  return (
    <Card>
      <div className="flex flex-col gap-5">
        <Field label="Template name">
          <input
            className={inputClass}
            value={name}
            maxLength={255}
            onChange={(event) => setName(event.target.value)}
            placeholder="Monthly newsletter"
          />
        </Field>

        <CampaignBodyEditor
          key={templateId ?? "new"}
          value={body}
          subject={name}
          onChange={setHtml}
        />

        <div className="flex items-center gap-3">
          <Button
            variant="primary"
            disabled={name.trim() === "" || body.trim() === "" || save.isPending}
            onClick={() => {
              if (templateId === null) {
                save.mutate({ name, html: body }, { onSuccess: onDone });
              } else {
                update.mutate(
                  { id: templateId, name, html: body },
                  { onSuccess: onDone },
                );
              }
            }}
          >
            {templateId === null ? "Save template" : "Save changes"}
          </Button>
          <Button onClick={onDone}>Cancel</Button>

          {error ? (
            <span className="text-caption text-danger">
              {error instanceof ApiError ? error.detail : error.message}
            </span>
          ) : null}
        </div>
      </div>
    </Card>
  );
}
