/**
 * Stage 3.2 exit criteria: "Known-answer test vectors confirm correct
 * encrypt/decrypt round-trip; confirm no derived key or plaintext
 * passphrase appears in any network request body except the intentional
 * per-request unlock use." The last part is a Stage 3.3 concern (this
 * module makes zero network calls, checked below) — nothing here ever
 * constructs an HTTP request.
 */
import { describe, expect, it, vi } from "vitest";
import {
  deriveKey,
  deriveKeyBytes,
  generateNonce,
  generateSalt,
  sealBytes,
  sealChunkWithKey,
  unsealBytes,
} from "./seal";

const encoder = new TextEncoder();

describe("deriveKey", () => {
  it("is deterministic for the same passphrase + salt", async () => {
    const salt = generateSalt();
    const keyA = await deriveKey("correct horse battery staple", salt);
    const keyB = await deriveKey("correct horse battery staple", salt);

    // Keys are non-extractable CryptoKeys, so compare by using each to
    // encrypt the same plaintext+nonce — identical ciphertext proves
    // identical underlying key bytes, without ever exporting the key.
    const nonce = generateNonce();
    const plaintext = encoder.encode("known-answer probe");
    const ctA = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: nonce },
      keyA,
      plaintext
    );
    const ctB = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: nonce },
      keyB,
      plaintext
    );
    expect(new Uint8Array(ctA)).toEqual(new Uint8Array(ctB));
  });

  it("derives a different key for a different salt", async () => {
    const nonce = generateNonce();
    const plaintext = encoder.encode("known-answer probe");

    const keyA = await deriveKey("same passphrase", generateSalt());
    const keyB = await deriveKey("same passphrase", generateSalt());

    const ctA = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: nonce },
      keyA,
      plaintext
    );
    const ctB = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: nonce },
      keyB,
      plaintext
    );
    expect(new Uint8Array(ctA)).not.toEqual(new Uint8Array(ctB));
  });

  it("produces a non-extractable AES-GCM key", async () => {
    const key = await deriveKey("passphrase", generateSalt());
    expect(key.extractable).toBe(false);
    expect(key.algorithm.name).toBe("AES-GCM");
    await expect(crypto.subtle.exportKey("raw", key)).rejects.toThrow();
  });

  it("matches a fixed known-answer vector (regression guard on Argon2id params)", async () => {
    // Fixed passphrase + salt -> fixed derived key -> fixed ciphertext
    // for a fixed plaintext + nonce. If this ever changes, the Argon2id
    // cost parameters (or the AES-GCM wiring) changed underneath callers
    // silently — anyone who sealed a file under the old parameters would
    // fail to unlock it.
    const salt = new Uint8Array(16); // all-zero, fixed
    const nonce = new Uint8Array(12); // all-zero, fixed
    const key = await deriveKey("known-answer-test-passphrase", salt);
    const ciphertext = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: nonce },
      key,
      encoder.encode("known-answer plaintext")
    );
    const hex = Buffer.from(ciphertext).toString("hex");
    expect(hex).toBe(
      "9857113140ae53f7cf8fed6a2878ba560f05a3f5cec53ab38be578a2eb17f2a1841f273fbff0"
    );
  });
});

describe("deriveKeyBytes", () => {
  it("is deterministic for the same passphrase + salt", async () => {
    const salt = generateSalt();
    const a = await deriveKeyBytes("correct horse battery staple", salt);
    const b = await deriveKeyBytes("correct horse battery staple", salt);
    expect(a).toEqual(b);
  });

  it("matches deriveKey's underlying key bytes exactly", async () => {
    // The unlock flow (deriveKeyBytes -> base64 -> sent to the server)
    // and the sealing flow (deriveKey -> a CryptoKey used locally) must
    // derive the exact same bytes from the same inputs, or a document
    // sealed under one path could never be unlocked under the other.
    const salt = generateSalt();
    const passphrase = "same underlying key either way";
    const rawBytes = await deriveKeyBytes(passphrase, salt);
    const cryptoKey = await deriveKey(passphrase, salt);

    const nonce = generateNonce();
    const plaintext = encoder.encode("known-answer probe");
    const importedKey = await crypto.subtle.importKey(
      "raw",
      rawBytes,
      { name: "AES-GCM" },
      false,
      ["encrypt"]
    );
    const ctFromRawBytes = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: nonce },
      importedKey,
      plaintext
    );
    const ctFromDeriveKey = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: nonce },
      cryptoKey,
      plaintext
    );
    expect(new Uint8Array(ctFromRawBytes)).toEqual(new Uint8Array(ctFromDeriveKey));
  });
});

describe("sealChunkWithKey — the multi-chunk document fix", () => {
  it("lets one shared key decrypt every chunk of a document", async () => {
    // The real bug this replaces: sealBytes() called once per chunk
    // gave every chunk its own fresh salt and therefore its own
    // different derived key, even though they share one passphrase —
    // only a document's first chunk could ever be correctly unsealed
    // again. One key, derived once, reused with a fresh nonce per
    // chunk (the standard AES-GCM pattern) is what actually lets every
    // chunk round-trip.
    const salt = generateSalt();
    const key = await deriveKey("one passphrase for the whole document", salt);
    const chunkTexts = ["first chunk", "second chunk, different content", "third"];

    const sealedChunks = await Promise.all(
      chunkTexts.map((text) => sealChunkWithKey(encoder.encode(text), key))
    );

    // Every chunk got its own nonce (never reused for the same key).
    const nonceHexes = sealedChunks.map((c) => Buffer.from(c.nonce).toString("hex"));
    expect(new Set(nonceHexes).size).toBe(chunkTexts.length);

    for (let i = 0; i < chunkTexts.length; i++) {
      const decrypted = await crypto.subtle.decrypt(
        { name: "AES-GCM", iv: sealedChunks[i].nonce },
        key,
        sealedChunks[i].ciphertext
      );
      expect(new TextDecoder().decode(decrypted)).toBe(chunkTexts[i]);
    }
  });
});

describe("sealBytes / unsealBytes round-trip", () => {
  it("recovers the original plaintext with the correct passphrase", async () => {
    const plaintext = encoder.encode(
      "The quick brown fox jumps over the lazy dog."
    );
    const sealed = await sealBytes(plaintext, "hunter2");
    const recovered = await unsealBytes(sealed, "hunter2");
    expect(recovered).toEqual(plaintext);
  });

  it("produces a fresh salt and nonce on every call", async () => {
    const plaintext = encoder.encode("same content, sealed twice");
    const first = await sealBytes(plaintext, "hunter2");
    const second = await sealBytes(plaintext, "hunter2");

    expect(first.salt).not.toEqual(second.salt);
    expect(first.nonce).not.toEqual(second.nonce);
    expect(first.ciphertext).not.toEqual(second.ciphertext);
  });

  it("throws on the wrong passphrase rather than returning garbage", async () => {
    const plaintext = encoder.encode("secret content");
    const sealed = await sealBytes(plaintext, "correct-passphrase");
    await expect(
      unsealBytes(sealed, "wrong-passphrase")
    ).rejects.toThrow();
  });

  it("throws if the ciphertext is tampered with", async () => {
    const plaintext = encoder.encode("secret content");
    const sealed = await sealBytes(plaintext, "hunter2");
    const tampered = new Uint8Array(sealed.ciphertext);
    tampered[0] ^= 0xff;
    await expect(
      unsealBytes({ ...sealed, ciphertext: tampered }, "hunter2")
    ).rejects.toThrow();
  });

  it("round-trips empty and binary (non-UTF8) content", async () => {
    const empty = new Uint8Array(0);
    const sealedEmpty = await sealBytes(empty, "hunter2");
    expect(await unsealBytes(sealedEmpty, "hunter2")).toEqual(empty);

    const binary = new Uint8Array([0, 255, 128, 1, 254, 17, 0, 0, 200]);
    const sealedBinary = await sealBytes(binary, "hunter2");
    expect(await unsealBytes(sealedBinary, "hunter2")).toEqual(binary);
  });
});

describe("no network calls", () => {
  it("never touches fetch while sealing or unsealing", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const plaintext = encoder.encode("never leaves the browser");
    const sealed = await sealBytes(plaintext, "hunter2");
    await unsealBytes(sealed, "hunter2");

    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
