/**
 * Stage 3.2 — client-side sealing. Everything here runs in the browser;
 * the passphrase and the key derived from it never leave this module.
 * Per CLAUDE.md: "The passphrase-derived key is client-side (WebCrypto)
 * and never persisted" — nothing here writes the key or the passphrase
 * to storage, and the only network call in the sealed-file flow (Stage
 * 3.3's unlock endpoint) sends a short-lived server-issued claim, never
 * the key or passphrase itself.
 *
 * WebCrypto's SubtleCrypto has no native Argon2id — it only ships
 * PBKDF2/HKDF/ECDH for key derivation — so Argon2id itself comes from
 * hash-wasm (a WASM build, no native bindings, browser-safe). The raw
 * bytes it derives are then imported as a non-extractable AES-GCM
 * CryptoKey via SubtleCrypto, which is what actually does the
 * encrypt/decrypt.
 */
import { argon2id } from "hash-wasm";

export const SALT_BYTES = 16;
export const NONCE_BYTES = 12; // AES-GCM's standard 96-bit nonce
const AES_KEY_BITS = 256;

// Argon2id cost parameters. OWASP's current baseline recommendation for
// Argon2id is >= 19 MiB memory, 2 iterations, 1 parallelism lane — these
// exceed that floor while staying fast enough for a browser (~200-400ms
// on typical hardware), since this runs on unlock, not on every request.
const ARGON2_ITERATIONS = 3;
const ARGON2_MEMORY_KIB = 65536; // 64 MiB
const ARGON2_PARALLELISM = 1;

// A Uint8Array's generic buffer type can widen to ArrayBufferLike
// (SharedArrayBuffer included) depending on how it was produced —
// SubtleCrypto's BufferSource type rejects that. Copying into a fresh
// Uint8Array always yields a plain ArrayBuffer-backed view.
function toBufferSource(bytes: Uint8Array): Uint8Array<ArrayBuffer> {
  return Uint8Array.from(bytes);
}

export function generateSalt(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(SALT_BYTES));
}

export function generateNonce(): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(NONCE_BYTES));
}

/** The Argon2id derivation alone, no WebCrypto import — the raw bytes a
 * document's unlock flow needs to send to the server as-is (base64),
 * since per CLAUDE.md/architecture-and-security.md the derived key
 * *does* transit to the server per unlock/unseal request (the server
 * decrypts there — that's the whole point of "not zero-knowledge").
 * deriveKey below wraps this for the sealing path, where a real
 * non-extractable CryptoKey is what's actually needed for
 * crypto.subtle.encrypt. Deterministic: the same passphrase + salt
 * always derives the same bytes, which is what lets a later unlock
 * re-derive the exact key from the same stored (non-secret) salt. */
export async function deriveKeyBytes(
  passphrase: string,
  salt: Uint8Array
): Promise<Uint8Array> {
  return argon2id({
    password: passphrase,
    salt,
    iterations: ARGON2_ITERATIONS,
    memorySize: ARGON2_MEMORY_KIB,
    parallelism: ARGON2_PARALLELISM,
    hashLength: AES_KEY_BITS / 8,
    outputType: "binary",
  });
}

/** Derives a non-extractable AES-256-GCM CryptoKey from a passphrase and
 * salt. Deterministic: the same passphrase + salt always derives the
 * same key, which is what lets a later unlock (Stage 3.3) re-derive the
 * key from the same salt instead of it ever being stored. */
export async function deriveKey(
  passphrase: string,
  salt: Uint8Array
): Promise<CryptoKey> {
  const rawKey = await deriveKeyBytes(passphrase, salt);
  return crypto.subtle.importKey(
    "raw",
    toBufferSource(rawKey),
    { name: "AES-GCM" },
    false,
    ["encrypt", "decrypt"]
  );
}

export interface SealedPayload {
  ciphertext: Uint8Array;
  salt: Uint8Array;
  nonce: Uint8Array;
}

/** Encrypts file bytes client-side. Generates a fresh salt (so deriveKey
 * output is scoped to this file) and a fresh nonce (AES-GCM's nonce must
 * never repeat for the same key). Fine for sealing a single standalone
 * payload; a multi-chunk document must NOT call this once per chunk —
 * see sealChunkWithKey below for why, and documents/page.tsx's
 * handleConfirmSeal for the real orchestration. */
export async function sealBytes(
  plaintext: Uint8Array,
  passphrase: string
): Promise<SealedPayload> {
  const salt = generateSalt();
  const nonce = generateNonce();
  const key = await deriveKey(passphrase, salt);

  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: toBufferSource(nonce) },
    key,
    toBufferSource(plaintext)
  );

  return { ciphertext: new Uint8Array(encrypted), salt, nonce };
}

export interface SealedChunkPayload {
  ciphertext: Uint8Array;
  nonce: Uint8Array;
}

/** Encrypts one chunk with an already-derived key — only the nonce is
 * fresh per call. This is the correct AES-GCM pattern for a multi-chunk
 * document: one key derived once (via deriveKey, from one salt), reused
 * across every chunk with a unique nonce each time, exactly what
 * unseal_document on the backend has only ever assumed (it decrypts
 * every chunk of a document with one caller-supplied key). A real bug
 * this replaces: sealing every chunk through sealBytes() independently
 * gave each one its own fresh salt and therefore its own different
 * derived key, even though they share one passphrase — the backend
 * could only ever correctly decrypt a document's first chunk. */
export async function sealChunkWithKey(
  plaintext: Uint8Array,
  key: CryptoKey
): Promise<SealedChunkPayload> {
  const nonce = generateNonce();
  const encrypted = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: toBufferSource(nonce) },
    key,
    toBufferSource(plaintext)
  );
  return { ciphertext: new Uint8Array(encrypted), nonce };
}

/** Decrypts a sealed payload given the same passphrase used to seal it.
 * Throws (AES-GCM auth tag mismatch) if the passphrase is wrong or the
 * ciphertext/nonce/salt were tampered with. */
export async function unsealBytes(
  payload: SealedPayload,
  passphrase: string
): Promise<Uint8Array> {
  const key = await deriveKey(passphrase, payload.salt);
  const decrypted = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: toBufferSource(payload.nonce) },
    key,
    toBufferSource(payload.ciphertext)
  );
  return new Uint8Array(decrypted);
}
