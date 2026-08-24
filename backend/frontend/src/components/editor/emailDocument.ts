/**
 * Wrapping composed content in a document a mail client will render.
 *
 * TipTap emits semantic HTML — <p>, <h1>, <ul>. Outlook renders that
 * inconsistently and Gmail strips anything it does not expect, so what leaves
 * the editor is not what should leave the building. This module puts the
 * content inside the shape email clients have always agreed on: a centred
 * single-column table with styles inlined on the elements themselves.
 *
 * The shell is not brand-styled. Mail clients drop <link> and mostly ignore
 * @font-face, and Outlook falls back to Times New Roman for a family it does
 * not know — so the stack names DM Sans first and degrades to faces that are
 * actually installed. The app is dark; the mail it produces is not.
 */

const FONT_STACK = "'DM Sans', 'Helvetica Neue', Helvetica, Arial, sans-serif";
const CONTENT_WIDTH = 600;

/** Marks a document this module produced, so it can be recognised on reopen. */
export const GENERATED_MARKER = "data-mailer-shell";

export interface EmailDocumentOptions {
  /** Shown in the preview header of some clients. */
  readonly title?: string;
}

export function buildEmailDocument(
  innerHtml: string,
  { title = "" }: EmailDocumentOptions = {},
): string {
  return `<!DOCTYPE html>
<html lang="en" ${GENERATED_MARKER}="1">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<title>${escapeHtml(title)}</title>
</head>
<body style="margin:0;padding:0;background-color:#f4f4f5;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f4f4f5;">
<tr>
<td align="center" style="padding:24px 12px;">
<table role="presentation" width="${CONTENT_WIDTH}" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:${CONTENT_WIDTH}px;background-color:#ffffff;border-radius:6px;">
<tr>
<td style="padding:32px;font-family:${FONT_STACK};font-size:16px;line-height:1.6;color:#1a1a1a;">
${innerHtml}
</td>
</tr>
</table>
</td>
</tr>
</table>
</body>
</html>`;
}

/**
 * Whether a body is a complete HTML document rather than a fragment.
 *
 * This is the test that decides authoring mode. A full document — anything
 * from a designer, from Maizzle, or from a pasted newsletter — must be left
 * exactly as it is: feeding it through a rich-text editor reparses it into the
 * editor's own schema and the table layout does not survive the round trip.
 */
export function isFullDocument(html: string): boolean {
  const head = html.slice(0, 2000).toLowerCase();

  if (head.includes("<!doctype") || head.includes("<html") || head.includes("<body")) {
    return true;
  }

  // A top-level table is the signature of a hand-built email layout even
  // without the surrounding document.
  return /^\s*(<!--[\s\S]*?-->\s*)*<table[\s>]/i.test(html);
}

/** Whether this document came out of buildEmailDocument. */
export function isGeneratedShell(html: string): boolean {
  return html.includes(GENERATED_MARKER);
}

/**
 * Recover the composed content from a document this module built, so a
 * compose-authored campaign can be reopened in the editor it was written in.
 * Returns null if the document is not one of ours.
 */
export function extractShellContent(html: string): string | null {
  if (!isGeneratedShell(html)) return null;

  const match = html.match(
    /color:#1a1a1a;">\n([\s\S]*?)\n<\/td>\n<\/tr>\n<\/table>/,
  );
  return match?.[1] ?? null;
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
