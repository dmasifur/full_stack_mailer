import { describe, expect, it } from "vitest";

import { MERGE_TAGS, tokensToChips } from "./MergeTag";

describe("MERGE_TAGS", () => {
  it("matches the fields the backend substitutes", () => {
    // Mirrors _FIELDS in backend/app/services/merge_fields.py. If that list
    // grows, this fails until they are brought back in step.
    expect(MERGE_TAGS.map((tag) => tag.token)).toEqual([
      "first_name",
      "last_name",
      "email",
    ]);
  });
});

describe("tokensToChips", () => {
  it("wraps a bare token", () => {
    expect(tokensToChips("Hi {{first_name}}")).toBe(
      'Hi <span data-merge-tag="first_name">{{first_name}}</span>',
    );
  });

  it("carries the fallback in its own attribute", () => {
    expect(tokensToChips("Hi {{first_name|there}}")).toBe(
      'Hi <span data-merge-tag="first_name" data-fallback="there">{{first_name|there}}</span>',
    );
  });

  it("tolerates whitespace inside the braces", () => {
    expect(tokensToChips("{{ email }}")).toContain('data-merge-tag="email"');
  });

  it("leaves an unknown token as plain text", () => {
    expect(tokensToChips("Hi {{nickname}}")).toBe("Hi {{nickname}}");
  });

  it("leaves content with no tokens untouched", () => {
    const body = "<p>No personalisation here</p>";

    expect(tokensToChips(body)).toBe(body);
  });

  it("wraps every occurrence", () => {
    const wrapped = tokensToChips("{{first_name}} {{last_name}}");

    expect(wrapped.match(/data-merge-tag/g)).toHaveLength(2);
  });
});
