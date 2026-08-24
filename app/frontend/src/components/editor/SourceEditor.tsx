/**
 * The HTML source half of the editor.
 *
 * What is typed or pasted here is stored byte for byte. That is the whole
 * point: a Maizzle build or a designer's table layout must reach the recipient
 * exactly as written, and any rich-text editor would reparse it into its own
 * schema and lose the layout on the way back out.
 */

import CodeMirror from "@uiw/react-codemirror";
import { html as htmlLanguage } from "@codemirror/lang-html";
import { useMemo } from "react";

import { Notice } from "@/components/ui/primitives";
import { isFullDocument } from "./emailDocument";

interface SourceEditorProps {
  readonly value: string;
  readonly onChange: (html: string) => void;
}

export function SourceEditor({ value, onChange }: SourceEditorProps) {
  const full = useMemo(() => isFullDocument(value), [value]);

  return (
    <div className="flex flex-col gap-3">
      {full ? (
        <Notice tone="info" title="Full email document">
          This is stored and sent exactly as written. Compose mode is locked for
          this campaign, because reparsing a table layout through a rich-text
          editor does not preserve it.
        </Notice>
      ) : null}

      <div className="overflow-hidden rounded-lg border border-border">
        <CodeMirror
          value={value}
          onChange={onChange}
          extensions={[htmlLanguage()]}
          theme="dark"
          height="32rem"
          basicSetup={{
            lineNumbers: true,
            foldGutter: true,
            highlightActiveLine: true,
            autocompletion: false,
          }}
        />
      </div>

      <p className="text-caption text-muted">
        Merge tags work here too — type <code>{"{{first_name|there}}"}</code>{" "}
        anywhere in the markup.
      </p>
    </div>
  );
}
