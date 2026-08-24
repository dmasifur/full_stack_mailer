import { describe, expect, it } from "vitest";

import { cleanPastedHtml, findDataUriImages } from "./pasteCleanup";

describe("cleanPastedHtml", () => {
  it("keeps the text and its structure", () => {
    const cleaned = cleanPastedHtml("<p>Hello <strong>world</strong></p>");

    expect(cleaned).toBe("<p>Hello <strong>world</strong></p>");
  });

  it("removes Word conditional comments", () => {
    const cleaned = cleanPastedHtml(
      "<!--[if gte mso 9]><xml>junk</xml><![endif]--><p>Real text</p>",
    );

    expect(cleaned).toBe("<p>Real text</p>");
  });

  it("removes the generated style block", () => {
    const cleaned = cleanPastedHtml(
      "<style>p.MsoNormal { margin: 0; }</style><p>Real text</p>",
    );

    expect(cleaned).toBe("<p>Real text</p>");
  });

  it("removes class and id attributes", () => {
    const cleaned = cleanPastedHtml('<p class="MsoNormal" id="x">Text</p>');

    expect(cleaned).toBe("<p>Text</p>");
  });

  it("removes Office namespaced elements", () => {
    expect(cleanPastedHtml("<p>Text<o:p></o:p></p>")).toBe("<p>Text</p>");
  });

  it("keeps real inline styles, which carry the formatting", () => {
    const cleaned = cleanPastedHtml('<p style="text-align:center">Text</p>');

    expect(cleaned).toContain("text-align:center");
  });

  it("strips mso declarations but keeps the rest of the style", () => {
    const cleaned = cleanPastedHtml(
      '<p style="mso-line-height-rule:exactly;color:red">Text</p>',
    );

    expect(cleaned).not.toContain("mso-");
    expect(cleaned).toContain("color:red");
  });

  it("drops a style attribute left empty after stripping", () => {
    const cleaned = cleanPastedHtml('<p style="mso-fareast-font-family:x">Text</p>');

    expect(cleaned).toBe("<p>Text</p>");
  });

  it("collapses the empty paragraphs Word uses for spacing", () => {
    const cleaned = cleanPastedHtml("<p>One</p><p>&nbsp;</p><p></p><p>Two</p>");

    expect(cleaned).toBe("<p>One</p><p>Two</p>");
  });

  it("removes meta and link elements", () => {
    const cleaned = cleanPastedHtml(
      '<meta charset="utf-8"><link rel="x"><p>Text</p>',
    );

    expect(cleaned).toBe("<p>Text</p>");
  });

  it("leaves an image element in place for the uploader to rewrite", () => {
    const cleaned = cleanPastedHtml('<p><img src="data:image/png;base64,AAA"></p>');

    expect(cleaned).toContain('src="data:image/png;base64,AAA"');
  });

  it("leaves merge tokens alone", () => {
    expect(cleanPastedHtml("<p>Hi {{first_name}}</p>")).toContain("{{first_name}}");
  });
});

describe("findDataUriImages", () => {
  it("finds every embedded image in order", () => {
    const found = findDataUriImages(
      '<p><img src="data:image/png;base64,AAA"></p>' +
        '<p><img src="data:image/jpeg;base64,BBB"></p>',
    );

    expect(found).toEqual([
      "data:image/png;base64,AAA",
      "data:image/jpeg;base64,BBB",
    ]);
  });

  it("ignores images already pointing at a URL", () => {
    const found = findDataUriImages('<img src="https://cdn.example.com/a.png">');

    expect(found).toEqual([]);
  });

  it("returns nothing for content with no images", () => {
    expect(findDataUriImages("<p>Text</p>")).toEqual([]);
  });
});
