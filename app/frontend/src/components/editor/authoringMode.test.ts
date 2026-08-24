import { describe, expect, it } from "vitest";

import { contentFor, modeFor } from "./authoringMode";
import { buildEmailDocument } from "./emailDocument";

describe("modeFor", () => {
  it("opens a new campaign in compose", () => {
    expect(modeFor("")).toBe("compose");
    expect(modeFor("   ")).toBe("compose");
  });

  it("opens a fragment in compose", () => {
    expect(modeFor("<p>Hello</p>")).toBe("compose");
  });

  it("reopens its own shell in compose", () => {
    expect(modeFor(buildEmailDocument("<p>Hello</p>"))).toBe("compose");
  });

  it("opens a pasted table template in source", () => {
    expect(modeFor('<table role="presentation"><tr><td>x</td></tr></table>')).toBe(
      "source",
    );
  });

  it("opens a full document in source", () => {
    expect(modeFor("<!DOCTYPE html><html><body>Hi</body></html>")).toBe("source");
  });
});

describe("contentFor", () => {
  it("hands source mode the whole document", () => {
    const document = "<!DOCTYPE html><html><body>Hi</body></html>";

    expect(contentFor(document, "source")).toBe(document);
  });

  it("unwraps its own shell for compose", () => {
    const content = "<h1>Launch</h1>";

    expect(contentFor(buildEmailDocument(content), "compose")).toBe(content);
  });

  it("passes a bare fragment through unchanged", () => {
    expect(contentFor("<p>Hello</p>", "compose")).toBe("<p>Hello</p>");
  });
});
