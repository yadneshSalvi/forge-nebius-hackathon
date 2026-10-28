import { useEffect, useState } from "react";
import { ArrowUpRight } from "lucide-react";
import { array, human, record, shortHash, str } from "./data";
import { Eyebrow, Status } from "./ui";
import type { Dict } from "./types";

export function GrootQualification() {
  const [qualification, setQualification] = useState<Dict | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    fetch("/groot-qualification.json", { signal: abort.signal })
      .then((response) => (response.ok ? response.json() : null))
      .then((value) => {
        if (!abort.signal.aborted) setQualification(value);
      })
      .catch(() => {});
    return () => abort.abort();
  }, []);
  return (
    <section className="groot-pending">
      <div className="groot-pending-mark">N</div>
      <div>
        <Eyebrow>NEXT ADAPTER / NOT YET QUALIFIED</Eyebrow>
        <h3>GR00T N1.7 + LIBERO Panda</h3>
        <p>
          GPU runtime qualification is pending. No GR00T action inference,
          camera-driven policy repair or learned GR00T result is claimed here.
        </p>
        {qualification ? (
          <details className="qualification-details">
            <summary>Inspect qualification gates</summary>
            <p>{str(qualification.scope)}</p>
            <dl>
              {array(qualification.gates).map((item) => {
                const gate = record(item);
                return (
                  <div key={str(gate.id)}>
                    <dt>
                      {human(gate.id)} <Status value={gate.status} />
                    </dt>
                    <dd>{str(gate.required_evidence)}</dd>
                  </div>
                );
              })}
            </dl>
            <p className="mono">
              Source {shortHash(str(qualification.source_revision))} ·
              Checkpoint {shortHash(str(qualification.checkpoint_revision))}
            </p>
            <a
              className="text-button"
              href={str(qualification.source_url)}
              target="_blank"
              rel="noreferrer"
            >
              Pinned NVIDIA integration guide <ArrowUpRight size={12} />
            </a>
          </details>
        ) : null}
      </div>
      <Status value="pending" label="Qualification pending" />
    </section>
  );
}
