-- Phase 3 Gate testing found a real, previously-undetected bug:
-- sealed_chunks.content_ciphertext/salt/nonce were declared `bytea`
-- (migration 0011), but the app writes and reads them as plain base64
-- TEXT strings through PostgREST's JSON REST interface everywhere —
-- sealed_storage.py never base64-decodes before sending to PostgREST,
-- and never re-encodes after reading from it; it treats these fields
-- as opaque base64 strings from end to end, only ever calling
-- base64.b64decode() on the way into AESGCM.decrypt().
--
-- PostgREST does not auto-decode a JSON string into `bytea` — writing
-- a JSON string to a bytea column stores it per Postgres's own bytea
-- input rules (effectively the string's own byte representation, not
-- base64-decoded), and reads it back as a `\x`-prefixed hex string,
-- which is not valid base64 at all. Every sealed document written
-- before this fix has a corrupted content_ciphertext/salt/nonce as a
-- result — confirmed live: reading one back and calling
-- base64.b64decode() on it raised a real binascii.Error, a 500, and
-- (more importantly) meant the legitimate owner could not unlock their
-- own content either. Not a security hole (nothing decrypts, for
-- anyone, including the owner) but a correctness bug that made the
-- whole sealed tier non-functional.
--
-- Fix: these columns just need to be `text` — the app already only
-- ever treats them as base64 strings, so this requires zero
-- application code changes, only the schema to match what the code
-- always assumed.

alter table sealed_chunks
  alter column content_ciphertext type text using encode(content_ciphertext, 'escape'),
  alter column salt type text using encode(salt, 'escape'),
  alter column nonce type text using encode(nonce, 'escape');
