-- Fixes the extension_in_public security advisory: vector was created in
-- the public schema by "create extension if not exists vector" in 0001.
alter extension vector set schema extensions;
