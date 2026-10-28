import { useEffect, useRef, useState } from "react";
import { ArrowRight, ArrowUpRight, LoaderCircle } from "lucide-react";
import { request } from "./api";
import { array, human, num, record, shortHash, str } from "./data";
import { ReplayPair } from "./Replay";
import {
  DefinitionList,
  Drawer,
  ErrorMessage,
  Eyebrow,
  Panel,
  SectionTitle,
  Status,
} from "./ui";
import type { Campaign, Dict, Report, ReportArm } from "./types";

const caseCache = new Map<string, Dict[]>();

export function RemainingFailures({
  report,
  arm,
  onEpisode,
}: {
  report: Report;
  arm: ReportArm;
  onEpisode: (id: string) => void;
}) {
  const strata = [arm.nominal, arm.shifted].filter(Boolean).map(record);
  const total = strata.reduce((s, r) => s + num(r.total), 0);
  const successes = strata.reduce((s, r) => s + num(r.successes), 0);
  const remaining = total - successes;
  const newRegressions = strata.reduce(
    (s, r) => s + num(record(r.paired).regressed),
    0,
  );
  const nomination = record(arm.nomination);
  const seed = nomination.seed ?? record(arm.nominal).checkpoint_seed;
  const sha = str(report.outcomes_sha, "");
  const key = `${sha}:${arm.name}:${seed}`;
  const [cases, setCases] = useState<Dict[] | null>(
    () => caseCache.get(key) || null,
  );
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const abort = useRef<AbortController | null>(null);
  useEffect(() => {
    setCases(caseCache.get(key) || null);
    setError("");
    setPending(false);
    return () => abort.current?.abort();
  }, [key]);
  async function load() {
    setPending(true);
    setError("");
    const controller = new AbortController();
    abort.current = controller;
    try {
      const artifact = await request<Dict>(`/artifacts/${sha}`, {
        signal: controller.signal,
      });
      const rows = array(artifact.rows)
        .map(record)
        .filter(
          (r) =>
            r.arm === arm.name &&
            r.training_seed === seed &&
            r.valid !== false &&
            r.success === false,
        )
        .map((r) => ({
          episode_id: r.episode_id,
          scenario_id: r.scenario_id,
          family: r.family,
          terminal_reason: r.terminal_reason,
          training_seed: r.training_seed,
          checkpoint_sha: r.checkpoint_sha,
        }));
      caseCache.set(key, rows);
      setCases(rows);
    } catch (err) {
      if (!controller.signal.aborted)
        setError(
          err instanceof Error
            ? err.message
            : "Could not read the verified case evidence.",
        );
    } finally {
      if (!controller.signal.aborted) setPending(false);
    }
  }
  if (!total) return null;
  const reasons = Object.entries(
    (cases || []).reduce<Record<string, number>>((counts, r) => {
      const name = str(r.terminal_reason, "unclassified");
      counts[name] = (counts[name] || 0) + 1;
      return counts;
    }, {}),
  );
  return (
    <section className="nominee-failures">
      <div className="nominee-failures-heading">
        <div>
          <Eyebrow>NOMINATED CHECKPOINT · SEED {str(seed)}</Eyebrow>
          <h3>
            {remaining} remaining {remaining === 1 ? "failure" : "failures"} in{" "}
            {total} registered scenarios.
          </h3>
          <p>
            {arm.label}: {successes} / {total} successes. {newRegressions} new
            regressions for this nominated checkpoint. The aggregate matrix
            retains the other training seeds separately.
          </p>
        </div>
        <span className="mono">
          {shortHash(str(nomination.checkpoint_sha, ""))}
        </span>
      </div>
      {remaining > 0 && !cases ? (
        <button
          className="text-button"
          disabled={pending || !sha}
          onClick={() => void load()}
        >
          {pending ? <LoaderCircle size={15} className="spin" /> : null}
          {pending
            ? "Reading verified outcomes…"
            : `Inspect ${remaining} remaining failures`}
          <ArrowRight size={15} />
        </button>
      ) : null}
      {cases ? (
        <>
          <p className="failure-reason-counts">
            {reasons.map(([reason, count]) => (
              <span key={reason}>
                <strong className="mono">{count}</strong>
                {human(reason)}
              </span>
            ))}
          </p>
          <ol className="nominee-case-list">
            {cases.map((r, i) => (
              <li key={str(r.episode_id, i.toString())}>
                <div>
                  <Status value="failure" label={human(r.terminal_reason)} />
                  <span>{human(r.family)}</span>
                </div>
                <button
                  className="text-button"
                  onClick={() => onEpisode(str(r.episode_id, ""))}
                >
                  Inspect case {i + 1}
                  <ArrowUpRight size={14} />
                </button>
              </li>
            ))}
          </ol>
          {cases.length !== remaining ? (
            <p className="field-help">
              The loaded case list contains {cases.length} verified rows; the
              report denominator above remains authoritative.
            </p>
          ) : null}
        </>
      ) : null}
      {error ? <ErrorMessage error={error} retry={() => void load()} /> : null}
    </section>
  );
}

export function SupplementaryReproductions({
  campaign,
}: {
  campaign: Campaign;
}) {
  const records = array(campaign.supplementary_reproductions).map(record);
  const [selected, setSelected] = useState<Dict | null>(null);
  const [camera, setCamera] = useState("perspective");
  if (!records.length) return null;
  return (
    <>
      <Panel className="supplementary-panel">
        <SectionTitle
          eyebrow="POST-FINAL REPRODUCTIONS"
          title="Inspect the broader regression evidence."
          detail="These fresh reproductions use frozen checkpoints and sit outside registered statistics and nomination."
        />
        <div className="supplementary-list">
          {records.map((r, i) => (
            <div key={str(r.evidence_sha, i.toString())}>
              <div>
                <h3>
                  {str(
                    r.label,
                    `Non-nominated seed ${str(r.training_seed)} · post-final reproduction`,
                  )}
                </h3>
                <p>{str(r.scope)}</p>
                <span className="mono">
                  {human(r.arm)} · checkpoint{" "}
                  {shortHash(str(r.checkpoint_sha, ""))}
                </span>
              </div>
              <button
                className="button button-quiet"
                onClick={() => setSelected(r)}
              >
                Open paired microscope
                <ArrowUpRight size={15} />
              </button>
            </div>
          ))}
        </div>
      </Panel>
      {selected ? (
        <Drawer
          title={str(selected.label, "Post-final paired reproduction")}
          eyebrow="SUPPLEMENTARY EVIDENCE · NON-NOMINATED CHECKPOINT"
          onClose={() => setSelected(null)}
          wide
        >
          <p className="drawer-intro">{str(selected.scope)}</p>
          <ReplayPair
            campaign={campaign}
            camera={camera}
            onCamera={setCamera}
            leftId={str(selected.base_episode_id, "")}
            rightId={str(selected.revised_episode_id, "")}
            leftLabel="Frozen base policy"
            rightLabel={`Revised · seed ${str(selected.training_seed)}`}
            compact
          />
          <DefinitionList
            entries={[
              ["Training seed", str(selected.training_seed)],
              [
                "Nomination",
                selected.nominated === false
                  ? "Non-nominated checkpoint"
                  : str(selected.nominated),
              ],
              [
                "Checkpoint",
                <span className="mono">
                  {shortHash(str(selected.checkpoint_sha, ""))}
                </span>,
              ],
              [
                "Scenario",
                <span className="mono">{str(selected.scenario_id)}</span>,
              ],
            ]}
          />
          {selected.evidence_sha ? (
            <a
              className="text-button"
              href={`/api/artifacts/${str(selected.evidence_sha)}`}
              target="_blank"
              rel="noreferrer"
            >
              Read the verified reproduction manifest
              <ArrowUpRight size={14} />
            </a>
          ) : null}
        </Drawer>
      ) : null}
    </>
  );
}

export function DevelopmentHistory({ campaign }: { campaign: Campaign }) {
  const history = array(campaign.development_history).map(record);
  if (!history.length) return null;
  return (
    <Panel className="history-panel">
      <SectionTitle
        eyebrow="RETAINED DEVELOPMENT HISTORY"
        title="Keep the earlier negative result."
        detail="Summary-only history preserves the original outcome and provenance."
      />
      {history.map((item, index) => (
        <article key={str(item.evidence_sha, index.toString())}>
          <h3>{str(item.label, "Earlier development experiment")}</h3>
          <p>{str(item.scope)}</p>
          <div className="table-scroll" tabIndex={0}>
            <table>
              <caption className="sr-only">
                Retained historical arm results
              </caption>
              <thead>
                <tr>
                  <th>Arm</th>
                  <th>Successes / executions</th>
                  <th>Rate</th>
                </tr>
              </thead>
              <tbody>
                {array(item.arms).map((value, i) => {
                  const arm = record(value);
                  return (
                    <tr key={i}>
                      <th>{str(arm.label, human(arm.name))}</th>
                      <td className="mono">
                        {str(arm.successes)} / {str(arm.total)}
                      </td>
                      <td className="mono">
                        {typeof arm.rate === "number"
                          ? `${(arm.rate * 100).toFixed(1)}%`
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p>{str(item.interpretation)}</p>
          <DefinitionList
            entries={[
              [
                "Original source",
                <span className="mono">
                  {shortHash(str(item.source_sha, ""))}
                </span>,
              ],
              [
                "Original protocol",
                <span className="mono">
                  {shortHash(str(item.protocol_sha, ""))}
                </span>,
              ],
              [
                "Original report digest",
                <span className="mono">
                  {str(item.original_report_digest)}
                </span>,
              ],
              [
                "Historical archive fingerprint",
                <span className="mono">
                  {shortHash(str(record(item.archive).sha256, ""))}
                </span>,
              ],
            ]}
          />
          {item.evidence_sha ? (
            <a
              className="text-button"
              href={`/api/artifacts/${str(item.evidence_sha)}`}
              target="_blank"
              rel="noreferrer"
            >
              Read the retained summary evidence
              <ArrowUpRight size={14} />
            </a>
          ) : null}
        </article>
      ))}
    </Panel>
  );
}
