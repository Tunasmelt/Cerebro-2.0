/**
 * Stage 7.10 — prepareCitationMarkersForMarkdown is the seam between
 * the [[chunk:<id>]] marker syntax the backend emits and the real
 * markdown renderer (components/AnswerMarkdown) that replaced the old
 * plain-text <span> rendering. Pure function, no React/DOM — the
 * existing parseAnswerSegments/stripCitationMarkers tests this file
 * would otherwise duplicate don't exist yet either, so this covers
 * both the pre-existing marker-splitting behavior and the new
 * markdown-link rewriting in one place.
 */
import { describe, expect, it } from "vitest";
import { prepareCitationMarkersForMarkdown } from "./citations";

describe("prepareCitationMarkersForMarkdown", () => {
  it("rewrites a resolved marker into a cite: link", () => {
    const text = "The sky is blue [[chunk:abc123]].";
    const result = prepareCitationMarkersForMarkdown(text, [{ chunk_id: "abc123" }]);

    expect(result).toBe("The sky is blue [cite](cite:abc123).");
  });

  it("drops an unresolved marker entirely, leaving no trace", () => {
    const text = "This is hallucinated [[chunk:not-real]].";
    const result = prepareCitationMarkersForMarkdown(text, [{ chunk_id: "abc123" }]);

    expect(result).toBe("This is hallucinated .");
  });

  it("drops every marker when citations is empty (the streaming case)", () => {
    const text = "Partial answer [[chunk:abc123]] still streaming";
    const result = prepareCitationMarkersForMarkdown(text, []);

    expect(result).toBe("Partial answer  still streaming");
  });

  it("URI-encodes a chunk id containing a colon (sealed-match id format)", () => {
    const text = "Sealed match [[chunk:doc-1:3]].";
    const result = prepareCitationMarkersForMarkdown(text, [{ chunk_id: "doc-1:3" }]);

    expect(result).toBe("Sealed match [cite](cite:doc-1%3A3).");
  });

  it("handles multiple markers, some resolved and some not", () => {
    const text = "First [[chunk:a]], second [[chunk:b]], third [[chunk:c]].";
    const result = prepareCitationMarkersForMarkdown(text, [
      { chunk_id: "a" },
      { chunk_id: "c" },
    ]);

    expect(result).toBe("First [cite](cite:a), second , third [cite](cite:c).");
  });

  it("leaves markdown-shaped text without any markers untouched", () => {
    const text = "**bold** and a [real link](https://example.com)";
    const result = prepareCitationMarkersForMarkdown(text, []);

    expect(result).toBe(text);
  });
});
