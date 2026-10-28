import { useEffect, useState } from "react";
import { Sparkles } from "lucide-react";
import { request } from "./api";
import { record, str } from "./data";
import { ErrorMessage, Eyebrow, JsonDetails } from "./ui";
import type { Dict } from "./types";
export function IncidentPlannerEvidence({
  receiptSha,
  outcome,
}: {
  receiptSha: string;
  outcome: string;
}) {
  const [receipt, setReceipt] = useState<Dict | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    setReceipt(null);
    setError("");
    request<Dict>(`/artifacts/${encodeURIComponent(receiptSha)}`, {
      signal: abort.signal,
    })
      .then(setReceipt)
      .catch((err) => {
        if (!abort.signal.aborted) setError(err.message);
      });
    return () => abort.abort();
  }, [receiptSha]);
  if (error) return <ErrorMessage error={`Saved planner receipt: ${error}`} />;
  if (!receipt) return null;
  const proposal = record(receipt.proposal);
  return (
    <section className="incident-planner-evidence">
      <Eyebrow>
        <Sparkles size={13} /> MODEL HYPOTHESIS → MEASURED INTERVENTION
      </Eyebrow>
      <div className="planner-provider-line">
        <strong>{str(receipt.provider)}</strong>
        <span className="mono">
          {str(receipt.returned_model ?? receipt.model)}
        </span>
      </div>
      {receipt.derivation ? (
        <p className="planner-derivation">
          Same model response · local schema correction · no new inference.
        </p>
      ) : null}
      <p>
        {str(proposal.hypothesis, "No hypothesis text in the bound receipt.")}
      </p>
      {proposal.competing_explanation ? (
        <p className="planner-alternative">
          <span>Competing explanation</span>
          {str(proposal.competing_explanation)}
        </p>
      ) : null}
      <div className="planner-measured-outcome">
        Observed result <strong>{outcome}</strong>
      </div>
      <small>
        Model prose proposes a test. Paired simulator outcomes establish the
        measured effect under this intervention.
      </small>
      <JsonDetails
        value={receipt}
        label="Inspect saved provider receipt and proposal"
      />
    </section>
  );
}
