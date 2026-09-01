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

/** Derives a non-extractable AES-256-GCM CryptoKey from a passphrase and
 * salt. Deterministic: the same passphrase + salt always derives the
 * same key, which is what lets a later unlock (Stage 3.3) re-derive the
 * key from the same salt instead of it ever being stored. */
export async function deriveKey(
  passphrase: string,
  salt: Uint8Array
): Promise<CryptoKey> {
  const rawKey = await argon2id({
    password: passphrase,
    salt,
    iterations: ARGON2_ITERATIONS,
    memorySize: ARGON2_MEMORY_KIB,
    parallelism: ARGON2_PARALLELISM,
    hashLength: AES_KEY_BITS / 8,
    outputType: "binary",
  });

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
 * never repeat for the same key). */
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
