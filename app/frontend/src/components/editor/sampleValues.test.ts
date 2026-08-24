import { describe, expect, it } from "vitest";

import { fillSampleValues } from "./sampleValues";

describe("fillSampleValues", () => {
  it("resolves the supported tokens", () => {
    expect(fillSampleValues("Hi {{first_name}} {{last_name}}")).toBe(
      "Hi Ada Lovelace",
    );
  });

  it("resolves the email token", () => {
    expect(fillSampleValues("{{email}}")).toBe("ada@example.com");
  });

  it("prefers the sample value over the fallback, as a real send would", () => {
    expect(fillSampleValues("Hi {{first_name|there}}")).toBe("Hi Ada");
  });

  it("tolerates whitespace inside the braces", () => {
    expect(fillSampleValues("Hi {{ first_name }}")).toBe("Hi Ada");
  });

  it("leaves an unknown token alone, matching the backend", () => {
    expect(fillSampleValues("Hi {{nickname}}")).toBe("Hi {{nickname}}");
  });

  it("leaves content with no tokens untouched", () => {
    const body = "<table><tr><td>Newsletter</td></tr></table>";

    expect(fillSampleValues(body)).toBe(body);
  });
});
