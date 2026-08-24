/**
 * Showing the email as a recipient will see it.
 *
 * The iframe is sandboxed with neither `allow-scripts` nor `allow-same-origin`,
 * which is why the backend does not sanitise `template_body`. Sanitising email
 * HTML hard enough to be safe also strips the tables and inline styles that
 * make it render in Outlook — so the body is stored exactly as written and the
 * *preview* is isolated instead. That boundary costs nothing and loses nothing.
 */

import { useMemo, useState } from "react";

import { Button } from "@/components/ui/primitives";
import { SAMPLE_RECIPIENT, fillSampleValues } from "./sampleValues";

const WIDTHS = {
  desktop: { label: "Desktop", px: 700 },
  mobile: { label: "Mobile", px: 390 },
} as const;

type WidthKey = keyof typeof WIDTHS;

export function PreviewPane({ html }: { html: string }) {
  const [width, setWidth] = useState<WidthKey>("desktop");
  const [filled, setFilled] = useState(true);

  const source = useMemo(
    () => (filled ? fillSampleValues(html) : html),
    [html, filled],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        {(Object.keys(WIDTHS) as WidthKey[]).map((key) => (
          <Button
            key={key}
            variant={width === key ? "primary" : "secondary"}
            onClick={() => setWidth(key)}
          >
            {WIDTHS[key].label}
          </Button>
        ))}
        <Button
          variant={filled ? "primary" : "secondary"}
          onClick={() => setFilled((on) => !on)}
          title="Show merge tags resolved with sample values"
        >
          Sample values
        </Button>
        {filled ? (
          <span className="text-caption text-muted">
            {`Showing ${SAMPLE_RECIPIENT}. Each recipient gets their own.`}
          </span>
        ) : null}
      </div>

      <div className="flex justify-center overflow-auto rounded-lg border border-border bg-canvas p-4">
        <iframe
          // No allow-scripts and no allow-same-origin: the body is arbitrary
          // HTML and it renders here with no access to this page or its cookies.
          sandbox=""
          srcDoc={source}
          title="Email preview"
          className="h-[70vh] border-0 bg-canvas"
          style={{ width: WIDTHS[width].px, maxWidth: "100%" }}
        />
      </div>
    </div>
  );
}
