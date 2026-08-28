"""Stage 0.1 stub mirror of packages/types/schema-version.json.

Reads the single JSON source of truth directly rather than duplicating the
value, so services/api and apps/web can never drift on SCHEMA_VERSION.
"""
import json
from pathlib import Path

_SCHEMA_VERSION_PATH = (
    Path(__file__).resolve().parents[3] / "packages" / "types" / "schema-version.json"
)

SCHEMA_VERSION: str = json.loads(_SCHEMA_VERSION_PATH.read_text())["SCHEMA_VERSION"]
