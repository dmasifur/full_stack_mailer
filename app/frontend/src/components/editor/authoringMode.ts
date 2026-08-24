/**
 * Deciding how a stored body should be opened.
 *
 * Kept apart from the editor component so the rule can be tested on its own —
 * it is the rule that stops a table-based email template being fed through a
 * rich-text schema and losing its layout.
 */

import { extractShellContent, isFullDocument } from "./emailDocument";

export type AuthoringMode = "compose" | "source";

/** Which mode a stored body should reopen in. */
export function modeFor(html: string): AuthoringMode {
  if (html.trim() === "") return "compose";
  return extractShellContent(html) !== null || !isFullDocument(html)
    ? "compose"
    : "source";
}

/** The editable content for a stored body, given its mode. */
export function contentFor(html: string, mode: AuthoringMode): string {
  if (mode === "source") return html;
  return extractShellContent(html) ?? html;
}
