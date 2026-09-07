/**
 * Post-launch fix: AnswerMarkdown originally rewrote [[chunk:<id>]]
 * markers into a markdown link and relied on ReactMarkdown's `a`
 * override to intercept a custom `cite:` scheme and swap in a real
 * citation-chip button. Live in production this didn't reliably fire —
 * the literal word "cite" rendered as plain link text, unclickable in
 * any useful way. Rewritten to render citation and text segments
 * directly via parseAnswerSegments instead (this module, unchanged
 * since Stage 1.7) — a real <button> with a real onClick, no markdown
 * or URI-scheme indirection at all. These tests cover the splitter
 * AnswerMarkdown now depends on directly, replacing the old
 * prepareCitationMarkersForMarkdown tests for the approach that was
 * removed.
 */
import { describe, expect, it } from "vitest";
import { parseAnswerSegments } from "./citations";

describe("parseAnswerSegments", () => {
  it("splits text around a single citation marker", () => {
    const segments = parseAnswerSegments("The sky is blue [[chunk:abc123]].");

    expect(segments).toEqual([
      { type: "text", text: "The sky is blue " },
      { type: "citation", chunkId: "abc123" },
      { type: "text", text: "." },
    ]);
  });

  it("handles multiple markers in one string", () => {
    const segments = parseAnswerSegments("First [[chunk:a]], second [[chunk:b]].");

    expect(segments).toEqual([
      { type: "text", text: "First " },
      { type: "citation", chunkId: "a" },
      { type: "text", text: ", second " },
      { type: "citation", chunkId: "b" },
      { type: "text", text: "." },
    ]);
  });

  it("returns a single text segment when there are no markers at all", () => {
    const segments = parseAnswerSegments("**bold** and a [real link](https://example.com)");

    expect(segments).toEqual([
      { type: "text", text: "**bold** and a [real link](https://example.com)" },
    ]);
  });

  it("handles a chunk id containing a colon (sealed-match id format)", () => {
    const segments = parseAnswerSegments("Sealed match [[chunk:doc-1:3]].");

    expect(segments).toEqual([
      { type: "text", text: "Sealed match " },
      { type: "citation", chunkId: "doc-1:3" },
      { type: "text", text: "." },
    ]);
  });

  it("handles a marker at the very start or end of the text", () => {
    expect(parseAnswerSegments("[[chunk:a]] leads")).toEqual([
      { type: "citation", chunkId: "a" },
      { type: "text", text: " leads" },
    ]);
    expect(parseAnswerSegments("trails [[chunk:a]]")).toEqual([
      { type: "text", text: "trails " },
      { type: "citation", chunkId: "a" },
    ]);
  });

  it("returns an empty array for empty input", () => {
    expect(parseAnswerSegments("")).toEqual([]);
  });

  it("splits the malformed multi-id group seen live into separate citation segments", () => {
    // Live in production, Gemini sometimes wrote [[chunk:id1], [chunk:id2]]
    // for one claim instead of two well-formed markers. The old regex
    // ([^\]]+, no ] allowed inside) stopped dead at the first inner ]
    // and left the whole group as unparsed, visibly raw text.
    const segments = parseAnswerSegments(
      "Two sources [[chunk:c1111111-1111-1111-1111-111111111111], [chunk:c2222222-2222-2222-2222-222222222222]]."
    );

    expect(segments).toEqual([
      { type: "text", text: "Two sources " },
      { type: "citation", chunkId: "c1111111-1111-1111-1111-111111111111" },
      { type: "citation", chunkId: "c2222222-2222-2222-2222-222222222222" },
      { type: "text", text: "." },
    ]);
  });

  it("still handles two well-formed markers written back to back", () => {
    const segments = parseAnswerSegments("Two sources [[chunk:a]][[chunk:b]].");

    expect(segments).toEqual([
      { type: "text", text: "Two sources " },
      { type: "citation", chunkId: "a" },
      { type: "citation", chunkId: "b" },
      { type: "text", text: "." },
    ]);
  });
});
