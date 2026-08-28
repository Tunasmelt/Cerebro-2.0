// Stage 0.1 stub. Full cross-language typing strategy (TS source of truth +
// generated JSON Schema for Pydantic) is deferred to when Stage 1.3 actually
// needs a shared chunk/document schema. For now, schema-version.json is the
// single value both apps/web and services/api read from this package.
import schemaVersion from "../schema-version.json";

export const SCHEMA_VERSION: string = schemaVersion.SCHEMA_VERSION;
