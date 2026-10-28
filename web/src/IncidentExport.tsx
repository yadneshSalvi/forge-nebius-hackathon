import { useState } from "react";
import { ArrowDownToLine, LoaderCircle } from "lucide-react";
import { record, str } from "./data";
import { ErrorMessage } from "./ui";

export function IncidentExport({ id }: { id: string }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [requested, setRequested] = useState(false);
  async function download() {
    if (pending) return;
    setPending(true);
    setError("");
    setRequested(false);
    try {
      const response = await fetch(
        `/api/incidents/${encodeURIComponent(id)}/export`,
      );
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        const detail = record(body).detail;
        throw new Error(
          str(
            typeof detail === "object" ? record(detail).message : detail,
            `Incident export failed (${response.status}). Please retry.`,
          ),
        );
      }
      const blob = await response.blob();
      if (!blob.size)
        throw new Error("The incident export was empty. Please retry.");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `forge-${id}-incident.zip`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setRequested(true);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "The incident test could not be downloaded. Please retry.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="fork-export-area">
      <button
        className="button button-primary fork-export"
        disabled={pending}
        aria-busy={pending}
        onClick={() => void download()}
      >
        {pending ? (
          <LoaderCircle size={16} className="spin" />
        ) : (
          <ArrowDownToLine size={16} />
        )}
        {pending
          ? "Preparing incident test…"
          : "Export executable incident test"}
      </button>
      {error ? (
        <ErrorMessage error={error} retry={() => void download()} />
      ) : null}
      <p className="fork-export-status" role="status" aria-live="polite">
        {pending
          ? "Preparing the recorded incident bundle."
          : requested
            ? "Incident test download requested."
            : ""}
      </p>
    </div>
  );
}
