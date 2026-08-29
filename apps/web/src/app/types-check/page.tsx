import { SCHEMA_VERSION } from "@cerebro/types";

export default function TypesCheckPage() {
  return (
    <>
      <p data-testid="schema-version">{SCHEMA_VERSION}</p>
      <p data-testid="stage-0-4-probe">vercel-deploy-check</p>
    </>
  );
}
