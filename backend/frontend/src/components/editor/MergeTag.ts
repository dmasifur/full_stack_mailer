/**
 * Merge tokens as chips.
 *
 * `{{first_name}}` is plain text as far as the document is concerned, and
 * plain text lets someone delete one brace without noticing. The mistake then
 * survives every review and shows up in a recipient's inbox. An atomic node
 * cannot be half-deleted: it goes in and out whole, and serialises back to the
 * exact token the backend's `render_merge_fields` looks for.
 */

import { Node, mergeAttributes } from "@tiptap/core";

export interface MergeTagDefinition {
  readonly token: string;
  readonly label: string;
  readonly description: string;
}

/** Mirrors _FIELDS in backend/app/services/merge_fields.py. */
export const MERGE_TAGS: readonly MergeTagDefinition[] = [
  {
    token: "first_name",
    label: "First name",
    description: "From the CSV's first_name column.",
  },
  {
    token: "last_name",
    label: "Last name",
    description: "From the CSV's last_name column.",
  },
  {
    token: "email",
    label: "Email address",
    description: "The recipient's address. Always present.",
  },
];

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    mergeTag: {
      insertMergeTag: (token: string, fallback?: string) => ReturnType;
    };
  }
}

function render(token: string, fallback: string): string {
  return fallback ? `{{${token}|${fallback}}}` : `{{${token}}}`;
}

export const MergeTag = Node.create({
  name: "mergeTag",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      token: {
        default: "first_name",
        parseHTML: (element) => element.getAttribute("data-merge-tag"),
      },
      // Shown when the recipient's value is blank. Worth encouraging: a CSV
      // almost always has rows with no first name.
      fallback: {
        default: "",
        // Round-tripped through its own attribute. Recovering it by
        // re-parsing the token text would break the moment the backend
        // substitutes a real value into it.
        parseHTML: (element) => element.getAttribute("data-fallback") ?? "",
      },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-merge-tag]" }];
  },

  renderHTML({ HTMLAttributes, node }) {
    const token = String(node.attrs.token);
    const fallback = String(node.attrs.fallback ?? "");

    // The span survives into the stored body and therefore into the email,
    // where it is inert — a bare <span> with data attributes renders as its
    // text in every client. It earns its place by letting a saved campaign
    // reopen with real chips instead of raw braces.
    return [
      "span",
      mergeAttributes(HTMLAttributes, {
        "data-merge-tag": token,
        ...(fallback ? { "data-fallback": fallback } : {}),
      }),
      render(token, fallback),
    ];
  },

  /**
   * What lands in the sent email.
   *
   * The chip is an editing affordance only — the body that reaches the backend
   * carries the bare token, because that is what the substitution matches.
   */
  renderText({ node }) {
    return render(String(node.attrs.token), String(node.attrs.fallback ?? ""));
  },

  addCommands() {
    return {
      insertMergeTag:
        (token: string, fallback = "") =>
        ({ commands }) =>
          commands.insertContent({
            type: this.name,
            attrs: { token, fallback },
          }),
    };
  },
});

/**
 * Replace tokens in stored HTML with chip markup, so reopening a saved body
 * shows chips rather than literal braces.
 */
export function tokensToChips(html: string): string {
  return html.replace(
    /\{\{\s*(\w+)\s*(?:\|([^}]*))?\}\}/g,
    (whole, token: string, fallback: string | undefined) => {
      if (!MERGE_TAGS.some((tag) => tag.token === token)) return whole;
      const attrs = fallback
        ? ` data-merge-tag="${token}" data-fallback="${fallback.trim()}"`
        : ` data-merge-tag="${token}"`;
      return `<span${attrs}>${whole}</span>`;
    },
  );
}
