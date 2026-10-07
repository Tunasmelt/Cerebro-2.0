import { expect, test } from "@playwright/test";

const chunkId = "11111111-1111-1111-1111-111111111111";
const documentId = "22222222-2222-2222-2222-222222222222";

function session() {
  const payload = Buffer.from(JSON.stringify({ sub: "user-1", exp: 4_102_444_800 })).toString("base64url");
  return {
    access_token: `eyJhbGciOiJub25lIn0.${payload}.signature`,
    refresh_token: "refresh",
    expires_at: 4_102_444_800,
    expires_in: 3600,
    token_type: "bearer",
    user: {
      id: "user-1", aud: "authenticated", role: "authenticated",
      email: "reader@example.com", user_metadata: {}, app_metadata: {},
    },
  };
}

test.beforeEach(async ({ page }) => {
  await page.context().addCookies([{
    name: "sb-test-auth-token",
    value: `base64-${Buffer.from(JSON.stringify(session())).toString("base64url")}`,
    domain: "127.0.0.1",
    path: "/",
    sameSite: "Lax",
  }]);
  await page.addInitScript((value) => {
    window.localStorage.setItem("sb-test-auth-token", JSON.stringify(value));
  }, session());
  await page.route("**/api/chat/sessions", (route) => route.fulfill({
    json: { sessions: [{ id: "session-1", created_at: "2026-10-08T00:00:00Z", preview: "Chart question" }] },
  }));
  await page.route("**/api/chat/sessions/session-1/messages", (route) => route.fulfill({
    json: { messages: [{
      id: "message-1", role: "assistant",
      content: `Revenue rose in Q4 [[chunk:${chunkId}]].`,
      retrieved_chunk_ids: [chunkId], retrieved_document_ids: [documentId],
      created_at: "2026-10-08T00:00:01Z",
      citations: [{ chunk_id: chunkId, document_id: documentId, document_title: "Quarterly report", page_number: 12, region_type: "chart", bbox: [.1, .2, .8, .7] }],
    }] },
  }));
  await page.route(`**/api/chunks/${chunkId}/evidence*`, (route) => route.fulfill({
    json: {
      chunk_id: chunkId,
      document: { id: documentId, title: "Quarterly report", layout_status: "partial" },
      surface: { page_number: 12, kind: "pdf_page" },
      surfaces: [{ page_number: 11 }, { page_number: 12 }, { page_number: 13 }],
      source_page_number: 12,
      region: { region_type: "chart", bbox: [.1, .2, .8, .7], content: "Revenue rose", semantic_summary: "Upward trend", text_start: null, text_end: null },
      heading_path: ["Results", "Revenue"], nearby: [], related: [],
      render_url: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='600' height='800'%3E%3Crect width='600' height='800' fill='white'/%3E%3C/svg%3E",
      legacy: false,
    },
  }));
});

test("citation opens owned evidence at the highlighted page and restores focus", async ({ page }, testInfo) => {
  await page.goto("/chat?session=session-1");
  const citation = page.getByTitle("Quarterly report");
  await expect(citation).toBeVisible();
  await citation.click();

  const drawer = page.getByRole("dialog", { name: "Citation evidence" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("Page 12")).toBeVisible();
  await expect(drawer.locator("span[class*='highlight']")).toBeVisible();
  await expect(drawer.getByText("2 / 3")).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("evidence.png"), fullPage: true });

  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(citation).toBeFocused();
});
