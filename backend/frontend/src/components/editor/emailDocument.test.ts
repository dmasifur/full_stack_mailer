import { describe, expect, it } from "vitest";

import {
  buildEmailDocument,
  extractShellContent,
  isFullDocument,
  isGeneratedShell,
} from "./emailDocument";

describe("buildEmailDocument", () => {
  it("puts the content inside the shell", () => {
    const document = buildEmailDocument("<p>Hello</p>");

    expect(document).toContain("<p>Hello</p>");
    expect(document).toContain("<!DOCTYPE html>");
  });

  it("uses a table layout, because mail clients do not do flexbox", () => {
    expect(buildEmailDocument("<p>Hi</p>")).toContain('role="presentation"');
  });

  it("names a font stack that degrades to installed faces", () => {
    const document = buildEmailDocument("<p>Hi</p>");

    expect(document).toContain("'DM Sans'");
    expect(document).toContain("Arial");
  });

  it("renders a light canvas regardless of the app's dark chrome", () => {
    expect(buildEmailDocument("<p>Hi</p>")).toContain("#ffffff");
  });

  it("escapes the title", () => {
    const document = buildEmailDocument("<p>Hi</p>", {
      title: '"><script>alert(1)</script>',
    });

    expect(document).not.toContain("<script>alert(1)</script>");
    expect(document).toContain("&lt;script&gt;");
  });

  it("leaves merge tokens untouched for the backend to resolve", () => {
    expect(buildEmailDocument("<p>Hi {{first_name}}</p>")).toContain(
      "{{first_name}}",
    );
  });
});

describe("isFullDocument", () => {
  it.each([
    ["<!DOCTYPE html><html><body>x</body></html>"],
    ["<html><body>x</body></html>"],
    ["<body>x</body>"],
    ['<table role="presentation"><tr><td>x</td></tr></table>'],
    ["  \n  <table><tr><td>x</td></tr></table>"],
    ["<!-- a comment --><table><tr><td>x</td></tr></table>"],
  ])("recognises %s as a full document", (html) => {
    expect(isFullDocument(html)).toBe(true);
  });

  it.each([
    ["<p>Just a paragraph</p>"],
    ["<h1>Heading</h1><p>and text</p>"],
    ["plain text"],
    [""],
    ["<p>A sentence mentioning a <table> tag inline</p>"],
  ])("treats %s as a fragment", (html) => {
    expect(isFullDocument(html)).toBe(false);
  });
});

describe("round trip", () => {
  it("recognises its own output", () => {
    expect(isGeneratedShell(buildEmailDocument("<p>Hi</p>"))).toBe(true);
  });

  it("does not claim a hand-written document", () => {
    expect(isGeneratedShell("<!DOCTYPE html><html><body>x</body></html>")).toBe(
      false,
    );
  });

  it("recovers the composed content", () => {
    const content = "<h1>Launch</h1><p>Hello {{first_name}}</p>";

    expect(extractShellContent(buildEmailDocument(content))).toBe(content);
  });

  it("returns null for a document it did not build", () => {
    expect(extractShellContent("<table><tr><td>x</td></tr></table>")).toBeNull();
  });
});
