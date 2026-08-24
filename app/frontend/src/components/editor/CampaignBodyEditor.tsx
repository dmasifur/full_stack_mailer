/**
 * The campaign body, in whichever mode it was authored.
 *
 * Compose and Source are not two views of one document. They are two ways of
 * authoring, and a campaign is in one of them:
 *
 *   - A body that is a full HTML document belongs to Source. Compose is locked,
 *     because reparsing table-based email markup through a rich-text schema
 *     does not give it back.
 *   - A compose-authored body is wrapped in the email shell on the way out, so
 *     what gets sent is a real email document rather than loose <p> tags.
 *
 * Compose → Source is offered one way, with a warning. Source → Compose is
 * offered only while the source is still a fragment.
 */

import { Suspense, lazy, useCallback, useMemo, useRef, useState } from "react";

import { Button, Notice, Spinner } from "@/components/ui/primitives";
import { type AuthoringMode, contentFor, modeFor } from "./authoringMode";
import { ComposeEditor } from "./ComposeEditor";
import { PreviewPane } from "./PreviewPane";
import { buildEmailDocument, isFullDocument } from "./emailDocument";

// CodeMirror is the largest dependency in the app and most campaigns never
// open this tab, so it is fetched on first use rather than at startup.
const SourceEditor = lazy(() =>
  import("./SourceEditor").then((module) => ({ default: module.SourceEditor })),
);

type Tab = AuthoringMode | "preview";

interface CampaignBodyEditorProps {
  /** The stored body. Empty for a new campaign. */
  readonly value: string;
  /** The body to store — already wrapped, if it was composed. */
  readonly onChange: (html: string) => void;
  readonly subject?: string;
}

export function CampaignBodyEditor({
  value,
  onChange,
  subject = "",
}: CampaignBodyEditorProps) {
  const initialMode = useRef(modeFor(value)).current;
  const [mode, setMode] = useState<AuthoringMode>(initialMode);
  const [tab, setTab] = useState<Tab>(initialMode);
  const [error, setError] = useState<string | null>(null);

  // Compose holds a fragment; Source holds the whole document. Kept apart so
  // switching mode is an explicit conversion rather than a silent one.
  const [fragment, setFragment] = useState(() => contentFor(value, "compose"));
  const [source, setSource] = useState(() =>
    initialMode === "source" ? value : "",
  );

  const composedDocument = useMemo(
    () => buildEmailDocument(fragment, { title: subject }),
    [fragment, subject],
  );

  const stored = mode === "source" ? source : composedDocument;
  const composeLocked = mode === "source" && isFullDocument(source);

  const handleFragmentChange = useCallback(
    (html: string) => {
      setFragment(html);
      onChange(buildEmailDocument(html, { title: subject }));
    },
    [onChange, subject],
  );

  const handleSourceChange = useCallback(
    (html: string) => {
      setSource(html);
      onChange(html);
    },
    [onChange],
  );

  function switchTo(next: Tab) {
    if (next === "preview" || next === mode) {
      setTab(next);
      return;
    }

    if (next === "source") {
      // One-way and lossless: the composed body is exported as the document it
      // would have been sent as.
      if (
        source === "" &&
        !window.confirm(
          "Switch to HTML source? The composed body is converted to markup. " +
            "Switching back is only possible while it stays a fragment.",
        )
      ) {
        return;
      }
      const exported = source === "" ? composedDocument : source;
      setSource(exported);
      onChange(exported);
      setMode("source");
      setTab("source");
      return;
    }

    if (composeLocked) return;

    setMode("compose");
    setTab("compose");
    onChange(buildEmailDocument(fragment, { title: subject }));
  }

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant={tab === "compose" ? "primary" : "secondary"}
          onClick={() => switchTo("compose")}
          disabled={composeLocked}
          title={
            composeLocked
              ? "This campaign holds a full HTML document. Editing it in Compose would not preserve the layout."
              : undefined
          }
        >
          Compose
        </Button>
        <Button
          variant={tab === "source" ? "primary" : "secondary"}
          onClick={() => switchTo("source")}
        >
          HTML source
        </Button>
        <Button
          variant={tab === "preview" ? "primary" : "secondary"}
          onClick={() => switchTo("preview")}
        >
          Preview
        </Button>
      </div>

      {composeLocked && tab !== "preview" ? (
        <Notice tone="info" title="Compose is locked for this campaign">
          The body is a complete HTML document, so it is stored and sent exactly
          as written. To compose instead, start a new campaign.
        </Notice>
      ) : null}

      {error ? (
        <Notice tone="danger" title="Image upload failed">
          {error}
        </Notice>
      ) : null}

      {tab === "compose" ? (
        <ComposeEditor
          initialContent={fragment}
          onChange={handleFragmentChange}
          onError={setError}
        />
      ) : null}

      {tab === "source" ? (
        <Suspense fallback={<Spinner label="Loading the source editor" />}>
          <SourceEditor value={source} onChange={handleSourceChange} />
        </Suspense>
      ) : null}

      {tab === "preview" ? <PreviewPane html={stored} /> : null}
    </section>
  );
}
