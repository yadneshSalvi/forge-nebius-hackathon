import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  Copy,
  Download,
  Fingerprint,
  LockKeyhole,
  ShieldCheck,
} from "lucide-react";
import { useState } from "react";
import {
  human,
  intervalText,
  percent,
  record,
  shortHash,
  str,
  textOf,
} from "./data";
import { Lineage, StratumTable } from "./Learning";
import {
  DevelopmentHistory,
  RemainingFailures,
  SupplementaryReproductions,
} from "./EvidenceCases";
import {
  DefinitionList,
  Empty,
  Eyebrow,
  JsonDetails,
  PageHeading,
  Panel,
  Status,
} from "./ui";
import type { Bootstrap, Campaign } from "./types";

export function Reports({
  campaign,
  bootstrap,
  onPolicies,
  onEpisode,
}: {
  campaign: Campaign | null;
  bootstrap: Bootstrap | null;
  onPolicies: () => void;
  onEpisode: (id: string) => void;
}) {
  const [development, setDevelopment] = useState(false);
  const registered = !!campaign?.registered_report && !development;
  const report = registered ? campaign?.registered_report : campaign?.report;
  const arm =
    report?.arms?.find((a) => a.name === report.selected_arm) ||
    report?.arms?.[0];
  const [copied, setCopied] = useState(false);
  const command = "python scripts/reproduce.py --bundle . --verify";
  async function copyCommand() {
    try {
      await navigator.clipboard.writeText(command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }
  return (
    <>
      <PageHeading
        number="06"
        label="RELIABILITY REPORT"
        title="A decision you can inspect."
        description="Read the supported claim, its distribution, the regressions, and the costs. Carry the exact evidence into the next review."
        actions={
          campaign ? (
            <a
              className="button button-primary"
              href={`/api/campaigns/${campaign.id}/export`}
              download
            >
              <Download size={16} />
              Export reproducibility bundle
            </a>
          ) : undefined
        }
      />
      {campaign?.registered_report ? (
        <div
          className="evaluation-switch"
          role="group"
          aria-label="Report evidence"
        >
          <button
            aria-pressed={!development}
            className={!development ? "selected" : ""}
            onClick={() => setDevelopment(false)}
          >
            Registered confirmation
          </button>
          <button
            aria-pressed={development}
            className={development ? "selected" : ""}
            onClick={() => setDevelopment(true)}
          >
            Development history
          </button>
        </div>
      ) : null}
      {!campaign ? (
        <Empty title="Select a campaign">
          Each experiment keeps its own report and reproducibility artifacts.
        </Empty>
      ) : !report ? (
        <>
          <Panel className="report-pending">
            <Eyebrow>THE REPORT IS AN OUTPUT OF THE EXPERIMENT</Eyebrow>
            <h2>The evidence is still being earned.</h2>
            <p>
              A report appears after validated demonstrations, actual policy
              training, and the registered development evaluation. Current
              stage: <strong>{human(campaign.stage)}</strong>.
            </p>
            <Status value={campaign.status} />
            <div className="pending-report-chapters">
              <span>01 · Supported scope</span>
              <span>02 · Measured comparison</span>
              <span>03 · Regressions and limits</span>
              <span>04 · Reproduction</span>
            </div>
          </Panel>
          <Lineage campaign={campaign} />
        </>
      ) : (
        <div className="report-layout">
          <article className="report-document">
            <div className="report-masthead">
              <span>FORGE / EXPERIMENT RECORD</span>
              <span className="mono">{report.id}</span>
            </div>
            <header className="report-cover">
              <Eyebrow>{report.label}</Eyebrow>
              <h2>{human(report.decision)}.</h2>
              <p className="report-claim">
                {arm
                  ? `${arm.label} achieved ${arm.successes} successes across ${arm.total} policy executions (${percent(arm.rate, 1)}), compared with ${percent(report.baseline.rate, 1)} for the frozen base.`
                  : "The completed experiment is available for review."}
              </p>
              <div className="report-scope">
                <ShieldCheck size={17} />
                <p>{textOf(report.scope)}</p>
              </div>
              <DefinitionList
                entries={[
                  ["Campaign", campaign.name],
                  ["Decision", <Status value={report.decision} />],
                  ["Selected arm", arm?.label || "None nominated"],
                  [
                    "Evidence protocol",
                    <span className="mono">
                      {shortHash(report.protocol_sha)}
                    </span>,
                  ],
                ]}
              />
            </header>
            <section id="report-decision" className="report-chapter">
              <Eyebrow>01 / DECISION AND SUPPORTED SCOPE</Eyebrow>
              <h3>What this run supports.</h3>
              <ul className="report-reasons">
                {report.decision_reasons?.map((reason, i) => (
                  <li key={i}>{reason}</li>
                ))}
              </ul>
              <p>
                {str(
                  report.claim,
                  "This report applies to the registered original Cartesian gantry task in local MuJoCo simulation. Its scope and release gate follow the frozen protocol.",
                )}
              </p>
              <div className="report-callout">
                <LockKeyhole size={19} />
                <div>
                  <strong>Development history is retained separately.</strong>
                  <p>
                    {str(
                      record(report.evaluation).scope,
                      registered
                        ? "This registered simulation confirmation uses the frozen nominated checkpoint and protocol. The exploratory development record remains available above."
                        : "The public development manifest is reused for exploration. It does not establish an independently registered confirmation result or qualify a hardware release.",
                    )}
                  </p>
                </div>
              </div>
            </section>
            <section id="report-results" className="report-chapter">
              <Eyebrow>02 / MEASURED POLICY COMPARISON</Eyebrow>
              <h3>The actual denominators.</h3>
              <div className="table-scroll" tabIndex={0}>
                <table>
                  <caption className="sr-only">
                    Actual measured policy results
                  </caption>
                  <thead>
                    <tr>
                      <th>Policy</th>
                      <th>Successes / executions</th>
                      <th>Rate</th>
                      <th>95% interval</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <th>
                        <span className="baseline-line" />
                        Frozen base
                      </th>
                      <td className="mono">
                        {report.baseline.successes} / {report.baseline.total}
                      </td>
                      <td className="mono">
                        {percent(report.baseline.rate, 1)}
                      </td>
                      <td>
                        {record(report.baseline).interval == null
                          ? "Descriptive pooled rate"
                          : intervalText(record(report.baseline).interval)}
                      </td>
                    </tr>
                    {report.arms.map((a) => (
                      <tr key={a.name}>
                        <th>
                          <span
                            className={`arm-line ${a.name === "minimized" ? "targeted-line" : ""}`}
                          />
                          {a.label}
                        </th>
                        <td className="mono">
                          {a.successes} / {a.total}
                        </td>
                        <td className="mono">{percent(a.rate, 1)}</td>
                        <td className="mono">
                          {a.interval == null
                            ? "Descriptive pooled rate"
                            : intervalText(a.interval)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p>
                Uncertainty methods, pairing, and scenario families are fixed by
                the protocol. Each arm retains its checkpoint seeds; repeated
                scenarios across seeds share the same frozen manifest. Model
                interpretation does not enter the numerical verdict.
              </p>
              {registered && arm && (arm.nominal || arm.shifted) ? (
                <div className="report-strata">
                  <h4>Separate registered strata</h4>
                  <StratumTable arm={arm} />
                </div>
              ) : null}
              <button className="text-button" onClick={onPolicies}>
                Inspect paired outcomes and checkpoints
                <ArrowRight size={15} />
              </button>
            </section>
            <section id="report-lineage" className="report-chapter">
              <Eyebrow>03 / EXPERIMENT LINEAGE</Eyebrow>
              <h3>Reconstruct the intervention.</h3>
              <p>
                The source failure, reduction trials, demonstration manifest,
                learned checkpoints, and report retain content hashes. New
                source or task revisions require a new campaign.
              </p>
              <DefinitionList
                entries={[
                  [
                    "Task spec",
                    <HashLink
                      hash={str(
                        campaign.task_artifact_sha ?? campaign.config.task_sha,
                        "",
                      )}
                    />,
                  ],
                  [
                    "Base checkpoint",
                    <HashLink
                      hash={str(campaign.config.base_checkpoint_sha, "")}
                    />,
                  ],
                  [
                    "Training curriculum",
                    <span className="mono">
                      {campaign.curriculum?.id || "Pending"}
                    </span>,
                  ],
                  [
                    "Evaluation manifest",
                    <HashLink hash={report.manifest_sha} />,
                  ],
                  [
                    "Registered protocol",
                    <HashLink hash={report.protocol_sha} />,
                  ],
                ]}
              />
              <JsonDetails
                value={campaign.training}
                label="Training seeds, budgets, and actual weight changes"
              />
            </section>
            <section id="report-regressions" className="report-chapter">
              <Eyebrow>04 / FAILURE CASES AND LIMITS</Eyebrow>
              <h3>Keep the boundary in view.</h3>
              <p>
                {report.regressions?.length ?? 0} regression replays are listed
                for the nominated checkpoints. The policy matrix retains all
                training seeds, including non-nominated checkpoint outcomes.
              </p>
              {registered && arm ? (
                <RemainingFailures
                  report={report}
                  arm={arm}
                  onEpisode={onEpisode}
                />
              ) : null}
              <SupplementaryReproductions campaign={campaign} />
              <ul className="report-limitations">
                {report.limitations?.map((limitation, i) => (
                  <li key={i}>{limitation}</li>
                ))}
              </ul>
              <p>
                The embodiment is an original gantry. Its learned policy uses
                instrumented state; the local runtime does not establish GR00T,
                Isaac, CUDA, or robot hardware qualification.
              </p>
            </section>
            <DevelopmentHistory campaign={campaign} />
            <section id="report-resources" className="report-chapter">
              <Eyebrow>05 / RESOURCE ACCOUNTING</Eyebrow>
              <h3>What the experiment consumed.</h3>
              <p>
                Successful demonstration count and optimizer updates are matched
                across arms. Search, reduction, unsuccessful acquisition, CPU
                execution, and model use are accounted for separately.
              </p>
              <ResourceSummary value={report.resources} />
              <JsonDetails
                value={campaign.model_evidence}
                label="Actual NVIDIA provider receipts and model evidence"
              />
            </section>
            <section id="report-reproduce" className="report-chapter">
              <Eyebrow>06 / REPRODUCTION</Eyebrow>
              <h3>Take the evidence with you.</h3>
              <p>
                The export includes canonical task and scene manifests, traces,
                learned checkpoints, the evaluation record, reproduction
                instructions, and SHA-256 checksums. Extract the archive,
                install its pinned Python requirements, and run the verification
                command from the extracted folder.
              </p>
              <div className="reproduction-command">
                <code>{command}</code>
                <button
                  className="icon-button"
                  aria-label={
                    copied
                      ? "Reproduction command copied"
                      : "Copy reproduction command"
                  }
                  onClick={() => void copyCommand()}
                >
                  {copied ? <Check size={16} /> : <Copy size={16} />}
                </button>
              </div>
              <a
                className="button button-primary"
                href={`/api/campaigns/${campaign.id}/export`}
                download
              >
                <Download size={15} />
                Download evidence bundle
              </a>
              <p className="field-help">
                Exporting or copying this command does not launch compute. The
                bundle documents a separate fresh physics replay command.
              </p>
            </section>
            <footer className="report-document-footer">
              <span>FORGE</span>
              <span>PHYSICAL AI / SIMULATION EVIDENCE</span>
              <span className="mono">{shortHash(report.manifest_sha)}</span>
            </footer>
          </article>
          <aside className="report-sidebar">
            <div className="report-side-status">
              <Fingerprint size={24} />
              <Eyebrow>IMMUTABLE EVIDENCE</Eyebrow>
              <Status value={report.decision} />
              <p>
                Read with the registered task, protocol, and evaluation
                boundary.
              </p>
            </div>
            <nav aria-label="Report chapters">
              <a href="#report-decision">
                01<span>Decision and scope</span>
                <ArrowDown size={12} />
              </a>
              <a href="#report-results">
                02<span>Measured comparison</span>
                <ArrowDown size={12} />
              </a>
              <a href="#report-lineage">
                03<span>Lineage</span>
                <ArrowDown size={12} />
              </a>
              <a href="#report-regressions">
                04<span>Failures and limits</span>
                <ArrowDown size={12} />
              </a>
              <a href="#report-resources">
                05<span>Resources</span>
                <ArrowDown size={12} />
              </a>
              <a href="#report-reproduce">
                06<span>Reproduce</span>
                <ArrowDown size={12} />
              </a>
            </nav>
            <div className="report-artifacts">
              <Eyebrow>VERIFIED ARTIFACTS</Eyebrow>
              <HashLink
                hash={report.manifest_sha}
                label="Evaluation manifest"
              />
              <HashLink hash={report.protocol_sha} label="Frozen protocol" />
              {campaign.artifacts?.slice(0, 6).map((a, i) => {
                const r = record(a);
                const sha =
                  typeof a === "string"
                    ? a
                    : str(r.sha ?? r.sha256 ?? r.hash, "");
                return sha ? (
                  <HashLink
                    key={i}
                    hash={sha}
                    label={str(r.label ?? r.kind ?? r.name, "Artifact")}
                  />
                ) : null;
              })}
              <JsonDetails value={bootstrap?.runtime} label="Runtime lock" />
            </div>
          </aside>
        </div>
      )}
    </>
  );
}
function HashLink({ hash, label }: { hash: string; label?: string }) {
  return hash ? (
    <a
      className="hash-link"
      href={`/api/artifacts/${hash}`}
      target="_blank"
      rel="noreferrer"
    >
      {label ? <span>{label}</span> : null}
      <span className="mono">{shortHash(hash)}</span>
      <ArrowUpRight size={12} />
    </a>
  ) : (
    <span className="muted">Pending</span>
  );
}

function ResourceSummary({ value }: { value: unknown }) {
  const r = record(value);
  const inference = record(r.nvidia_inference);
  const entries: [string, React.ReactNode][] = [];
  if (typeof r.simulation_episodes === "number")
    entries.push([
      "Physical simulation episodes",
      r.simulation_episodes.toLocaleString(),
    ]);
  if (typeof r.training_seconds === "number")
    entries.push([
      "Total recorded training time",
      `${r.training_seconds.toFixed(3)} s`,
    ]);
  if (typeof inference.calls === "number")
    entries.push(["NVIDIA inference calls", inference.calls]);
  if (typeof inference.prompt_tokens === "number")
    entries.push([
      "Model input / output tokens",
      `${inference.prompt_tokens.toLocaleString()} / ${typeof inference.completion_tokens === "number" ? inference.completion_tokens.toLocaleString() : "—"}`,
    ]);
  if (typeof inference.known_estimated_cost_usd === "number")
    entries.push([
      "Known model cost estimate",
      `US$ ${inference.known_estimated_cost_usd.toFixed(6)}`,
    ]);
  return (
    <>
      <DefinitionList entries={entries} />
      <JsonDetails value={value} label="Full resource accounting by stage" />
    </>
  );
}
