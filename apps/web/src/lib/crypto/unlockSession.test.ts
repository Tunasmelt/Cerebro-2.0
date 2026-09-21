import { describe, expect, it } from "vitest";
import { forgetUnlock, getActiveUnlocks, rememberUnlock } from "./unlockSession";

describe("in-memory sealed unlock registry", () => {
  it("returns active claims and removes expired claims", () => {
    rememberUnlock({ document_id: "active", claim_id: "c1", key: "k1", expires_at: "2030-01-01T00:00:00Z" });
    rememberUnlock({ document_id: "expired", claim_id: "c2", key: "k2", expires_at: "2020-01-01T00:00:00Z" });

    expect(getActiveUnlocks(Date.parse("2029-01-01T00:00:00Z"))).toEqual([
      { document_id: "active", claim_id: "c1", key: "k1", expires_at: "2030-01-01T00:00:00Z" },
    ]);
    forgetUnlock("active");
    expect(getActiveUnlocks()).toEqual([]);
  });
});
