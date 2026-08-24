/**
 * Resolving merge tokens for the preview.
 *
 * Deliberately mirrors `render_merge_fields` in
 * server/services/merge_fields.py, fallback syntax included: a preview
 * that ignored the fallback would show a blank where a real send shows a word.
 */

import { MERGE_TAGS } from "./MergeTag";

const SAMPLE: Record<string, string> = {
  first_name: "Ada",
  last_name: "Lovelace",
  email: "ada@example.com",
};

export const SAMPLE_RECIPIENT = "Ada Lovelace";

export function fillSampleValues(html: string): string {
  return html.replace(
    /\{\{\s*(\w+)\s*(?:\|([^}]*))?\}\}/g,
    (whole, token: string, fallback: string | undefined) => {
      if (!MERGE_TAGS.some((tag) => tag.token === token)) return whole;
      return SAMPLE[token] ?? fallback?.trim() ?? "";
    },
  );
}
