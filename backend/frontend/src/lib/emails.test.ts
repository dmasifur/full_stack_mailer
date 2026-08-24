import { describe, expect, it } from "vitest";

import { splitEmails } from "./emails";

describe("splitEmails", () => {
  it("splits on commas", () => {
    expect(splitEmails("a@x.com, b@x.com")).toEqual(["a@x.com", "b@x.com"]);
  });

  it("splits on semicolons and newlines, which people paste", () => {
    expect(splitEmails("a@x.com;b@x.com\nc@x.com")).toEqual([
      "a@x.com",
      "b@x.com",
      "c@x.com",
    ]);
  });

  it("drops empty entries from a trailing separator", () => {
    expect(splitEmails("a@x.com, ,")).toEqual(["a@x.com"]);
  });

  it("returns nothing for an empty field", () => {
    expect(splitEmails("")).toEqual([]);
  });
});
