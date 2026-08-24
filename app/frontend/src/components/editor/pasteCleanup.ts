/**
 * Cleaning HTML on its way in from the clipboard.
 *
 * A paste from Word or Google Docs carries far more than the text: Office
 * conditional comments, `mso-*` declarations, an entire <style> block of
 * generated class names, and `class` attributes referencing them. ProseMirror
 * would drop most of it eventually, but the leftovers reach the emitted HTML
 * and end up in someone's inbox.
 *
 * This runs before ProseMirror parses, so it works on the string.
 */

/** Word wraps chunks of markup in <!--[if ...]> ... <![endif]--> blocks. */
const CONDITIONAL_COMMENT = /<!--\[if[\s\S]*?<!\[endif\]-->/gi;

/** Whole <style> and <meta>/<link> elements, contents included. */
const STYLE_BLOCK = /<style[\s\S]*?<\/style>/gi;
const HEAD_NOISE = /<(?:meta|link)\b[^>]*>/gi;

/** Office and Docs namespaced elements, e.g. <o:p></o:p>, <w:sdt>. */
const NAMESPACED_TAG = /<\/?[a-z]+:[a-z-]+[^>]*>/gi;

/** class= and id= attributes, whether quoted with " or '. */
const CLASS_OR_ID = /\s(?:class|id)\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+)/gi;

/** Word leaves `lang=`, `style="mso-..."` and `data-*` bookkeeping behind. */
const MSO_DECLARATIONS = /(?:^|;)\s*mso-[^;:]*:[^;]*/gi;

/**
 * Strip clipboard noise, keeping structure and text.
 *
 * Deliberately conservative about what it removes: inline `style` survives
 * except for its `mso-*` declarations, because that is where a pasted
 * document's real formatting lives.
 */
export function cleanPastedHtml(html: string): string {
  let cleaned = html
    .replace(CONDITIONAL_COMMENT, "")
    .replace(STYLE_BLOCK, "")
    .replace(HEAD_NOISE, "")
    .replace(NAMESPACED_TAG, "")
    .replace(CLASS_OR_ID, "");

  // The leading \s* is consumed too, so removing an all-mso style attribute
  // does not leave "<p >" behind.
  cleaned = cleaned.replace(/\s*style\s*=\s*"([^"]*)"/gi, (_whole, declarations: string) => {
    const kept = declarations.replace(MSO_DECLARATIONS, "").replace(/^;\s*/, "").trim();
    return kept ? ` style="${kept}"` : "";
  });

  // Word emits runs of empty paragraphs to fake spacing.
  cleaned = cleaned.replace(/<p[^>]*>(?:\s|&nbsp;|<br\s*\/?>)*<\/p>/gi, "");

  return cleaned.trim();
}

/**
 * Every image the clipboard carried as data, in document order.
 *
 * Word and Google Docs embed pasted images as data: URIs rather than as
 * separate files, so this is the only place they can be found before they are
 * uploaded and rewritten to public URLs.
 */
export function findDataUriImages(html: string): string[] {
  const found: string[] = [];
  const pattern = /<img\b[^>]*\bsrc\s*=\s*"(data:image\/[^"]+)"/gi;

  let match: RegExpExecArray | null;
  while ((match = pattern.exec(html)) !== null) {
    const uri = match[1];
    if (uri !== undefined) found.push(uri);
  }

  return found;
}

/** Turn a data: URI into a File the upload endpoint will accept. */
export async function dataUriToFile(uri: string, name: string): Promise<File> {
  const response = await fetch(uri);
  const blob = await response.blob();
  return new File([blob], name, { type: blob.type });
}
