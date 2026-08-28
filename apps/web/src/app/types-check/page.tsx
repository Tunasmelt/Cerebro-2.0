import { SCHEMA_VERSION } from "@cerebro/types";

export default function TypesCheckPage() {
  return <p data-testid="schema-version">{SCHEMA_VERSION}</p>;
}
