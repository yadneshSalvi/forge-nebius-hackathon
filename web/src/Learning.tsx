import { useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Download,
  FileCode2,
  GitBranch,
  GraduationCap,
  LockKeyhole,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import {
  activeStatus,
  differenceIntervalText,
  fixed,
  human,
  intervalText,
  percent,
  record,
  shortHash,
  str,
} from "./data";
import { ReplayPair } from "./Replay";
import { RemainingFailures, SupplementaryReproductions } from "./EvidenceCases";
import { ChallengeForm, ChallengeOutcome } from "./Challenge";
import {
  DefinitionList,
  Drawer,
  Empty,
  Eyebrow,
  JsonDetails,
  PageHeading,
  Panel,
  SectionTitle,
  Status,
} from "./ui";
import type {
  Bootstrap,
  Campaign,
  Dict,
  ReportArm,
  TrainingRun,
} from "./types";

export function Curricula({
  campaign,
  onTrain,
  onEpisode,
}: {
  campaign: Campaign | null;
  onTrain: () => void;
  onEpisode: (id: string) => void;
}) {
  const c = campaign?.curriculum;
  const [arm, setArm] = useState("all");
  const demonstrations = c?.demonstrations || [];
  const clusters = c?.failure_clusters || [];
  const filtered =
    arm === "all"
      ? demonstrations
      : demonstrations.filter((d) => d.arm === arm);
  const canTrain =
    !!demonstrations.some((d) => d.success) &&
    !campaign?.training?.runs?.length &&
    !activeStatus(campaign?.status);
  return (
    <>
      <PageHeading
        number="04"
        label="CORRECTIVE CURRICULA"
        title="Good data has a history."
        description="Trace every successful demonstration from its physical episode to a registered training arm. Preserve nominal behavior and keep evaluation families out."
        actions={
          <button
            className="button button-primary"
            disabled={!canTrain}
            onClick={onTrain}
          >
            <GraduationCap size={17} />
            Review training
            <ArrowRight size={15} />
          </button>
        }
      />
      {!campaign ? (
        <Empty title="Choose a campaign">
          Its curriculum will retain demonstration provenance and exclusions.
        </Empty>
      ) : !c ? (
        <>
          <Panel className="curriculum-pending">
            <Eyebrow>ACQUISITION FOLLOWS REDUCTION</Eyebrow>
            <h2>
              A failure is evidence.
              <br />A successful action is training data.
            </h2>
            <p>
              The worker first confirms a counterexample, then runs the
              validated expert to acquire genuinely successful corrective
              trajectories.
            </p>
            <Status value={campaign.status} label={human(campaign.stage)} />
          </Panel>
          <Lineage campaign={campaign} />
        </>
      ) : (
        <>
          <div className="curriculum-manifest">
            <div>
              <Eyebrow>IMMUTABLE MANIFEST</Eyebrow>
              <h2>{c.id}</h2>
              <span className="mono">
                BASE {shortHash(c.base_checkpoint_sha)}
              </span>
            </div>
            <div className="manifest-count">
              <strong className="mono">
                {demonstrations.filter((d) => d.success).length}
              </strong>
              <span>validated trajectories</span>
            </div>
            <div className="manifest-count">
              <strong className="mono">{c.arms?.length ?? 0}</strong>
              <span>registered arms</span>
            </div>
            <Status value={c.status} />
          </div>
          {clusters.length ? (
            <Panel className="cluster-provenance">
              <SectionTitle
                eyebrow="FROZEN ACQUISITION DESIGN"
                title={`${clusters.length} measured failure clusters.`}
                detail={
                  typeof c.design === "string"
                    ? c.design
                    : "The curriculum preserves each confirmed failure cluster and the declared correction allocation."
                }
              />
              <div className="cluster-provenance-list">
                {clusters.map((cluster, index) => {
                  const r = record(cluster);
                  const boundary =
                    index === 0
                      ? campaign.counterexample
                      : campaign.counterexample?.secondary_boundaries?.[
                          index - 1
                        ];
                  const id = str(
                    r.source_episode_id,
                    boundary?.source_episode_id || "",
                  );
                  return (
                    <div key={index}>
                      <span className="mono">
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <div>
                        <h3>{clusterLabel(cluster, index)}</h3>
                        {id ? (
                          <button
                            className="text-button"
                            onClick={() => onEpisode(id)}
                          >
                            Inspect source episode
                            <ArrowUpRight size={14} />
                          </button>
                        ) : null}
                      </div>
                    </div>
                  );
                })}
              </div>
              {c.paired_acquisition_sha ? (
                <a
                  className="hash-link"
                  href={`/api/artifacts/${c.paired_acquisition_sha}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  <span>Paired acquisition manifest</span>
                  <span className="mono">
                    {shortHash(c.paired_acquisition_sha)}
                  </span>
                  <ArrowUpRight size={13} />
                </a>
              ) : null}
              <JsonDetails
                value={{
                  failure_clusters: c.failure_clusters,
                  design: c.design,
                  paired_acquisition_sha: c.paired_acquisition_sha,
                  allocations: c.arms.map((a) => ({
                    arm: a.name,
                    cluster_allocation: a.cluster_allocation,
                  })),
                }}
                label="Cluster provenance and matched acquisition plan"
              />
            </Panel>
          ) : null}
          <div className="curriculum-arms">
            {c.arms?.map((a, i) => {
              const total = a.corrective + a.retained_nominal;
              return (
                <Panel key={a.name} className={`curriculum-arm arm-${i}`}>
                  <div className="arm-index mono">
                    {String(i + 1).padStart(2, "0")}
                    <GitBranch size={17} />
                  </div>
                  <Eyebrow>
                    {a.name === "minimized"
                      ? "TARGETED INTERVENTION"
                      : a.name === "source"
                        ? "REDUCTION ABLATION"
                        : "ACQUISITION CONTROL"}
                  </Eyebrow>
                  <h2>{a.label}</h2>
                  <p>
                    {a.name === "minimized"
                      ? clusters.length > 1
                        ? `Successful expert actions across all ${clusters.length} reduced boundaries. Paired noncausal backgrounds, nuisance draws, and broad severity coverage are matched to the source arm.`
                        : "Validated expert corrections near the reduced boundary."
                      : a.name === "source"
                        ? clusters.length > 1
                          ? `Successful expert actions across all ${clusters.length} original failure boundaries. Noncausal backgrounds and nuisance draws are paired with the minimized arm, with broad severity coverage.`
                          : "Expert corrections near the original failure before reduction."
                        : "Expert corrections sampled from the registered development envelope."}
                  </p>
                  <div
                    className="mixture-bar"
                    role="img"
                    aria-label={`${a.corrective} corrective and ${a.retained_nominal} nominal demonstrations`}
                  >
                    <span
                      style={{
                        width: `${total ? (a.corrective / total) * 100 : 0}%`,
                      }}
                    />
                  </div>
                  <div className="mixture-legend">
                    <span>
                      <i />
                      {a.corrective} corrective
                    </span>
                    <span>
                      <i />
                      {a.retained_nominal} nominal
                    </span>
                  </div>
                  <DefinitionList
                    entries={[
                      ["Accepted demonstrations", a.accepted],
                      ["Rejected attempts", a.rejected],
                      ["Acquisition episodes", a.acquisition_episodes],
                      ...allocationEntries(a.cluster_allocation, clusters),
                    ]}
                  />
                  <button
                    className="text-button"
                    onClick={() => setArm(a.name)}
                  >
                    Inspect trajectories
                    <ArrowRight size={14} />
                  </button>
                </Panel>
              );
            })}
          </div>
          <div className="curriculum-method">
            <Panel>
              <SectionTitle
                eyebrow="BEFORE ANY OPTIMIZER UPDATE"
                title="The experiment is frozen."
              />
              <DefinitionList
                entries={[
                  [
                    "Base initialization",
                    <span className="mono">
                      {shortHash(c.base_checkpoint_sha)}
                    </span>,
                  ],
                  [
                    "Training status",
                    <Status value={campaign.training?.status ?? "pending"} />,
                  ],
                  ["Budget source", "Registered local protocol"],
                ]}
              />
              <JsonDetails
                value={c.training_budget}
                label="Inspect fixed training budget"
              />
              <p className="method-note">
                The match covers successful demonstration count and optimizer
                updates. Search and failed acquisition costs are reported
                separately.
              </p>
            </Panel>
            <Panel className="exclusions-panel">
              <SectionTitle
                eyebrow="EVALUATION BOUNDARY"
                title="Keep the test outside the lesson."
              />
              <div className="exclusion-list">
                {c.excluded_splits?.map((split) => (
                  <div key={split}>
                    <LockKeyhole size={16} />
                    <span>{human(split)}</span>
                    <span>Excluded</span>
                  </div>
                ))}
              </div>
              <p>
                Held-out labels never enter the planner or training data. A
                trajectory must pass the same task predicate before inclusion.
              </p>
            </Panel>
          </div>
          <Lineage campaign={campaign} />
          <Panel className="demonstration-ledger">
            <SectionTitle
              eyebrow="VALIDATED ACTION DATA"
              title="Demonstration provenance"
            >
              <label className="select-label">
                <span className="sr-only">Filter demonstration arm</span>
                <select value={arm} onChange={(e) => setArm(e.target.value)}>
                  <option value="all">All registered arms</option>
                  {c.arms?.map((a) => (
                    <option key={a.name} value={a.name}>
                      {a.label}
                    </option>
                  ))}
                </select>
              </label>
            </SectionTitle>
            <div
              className="table-scroll"
              tabIndex={0}
              aria-label="Demonstration lineage table"
            >
              <table>
                <caption className="sr-only">
                  Demonstrations, source physical episodes, data split, and
                  validation
                </caption>
                <thead>
                  <tr>
                    <th>Trajectory</th>
                    <th>Arm / split</th>
                    <th>Provenance</th>
                    <th>Task oracle</th>
                    <th>Physical evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((d) => (
                    <tr key={`${d.id}-${d.arm}`}>
                      <td>
                        <span className="mono">{d.id.slice(-14)}</span>
                        <small className="table-subtext mono">
                          {shortHash(d.trajectory_sha)}
                        </small>
                      </td>
                      <td>
                        {human(d.arm)}
                        <small className="table-subtext">
                          {human(d.split)}
                        </small>
                      </td>
                      <td>{human(d.source)}</td>
                      <td>
                        <Status
                          value={d.success ? "success" : "failure"}
                          label={d.success ? "Validated success" : "Rejected"}
                        />
                      </td>
                      <td>
                        {d.episode_id ? (
                          <button
                            className="text-button"
                            onClick={() =>
                              d.episode_id && onEpisode(d.episode_id)
                            }
                          >
                            Inspect episode
                            <ArrowUpRight size={13} />
                          </button>
                        ) : (
                          <a
                            className="text-button"
                            href={`/api/artifacts/${d.trajectory_sha}`}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Trajectory manifest
                            <ArrowUpRight size={13} />
                          </a>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="table-caption mono">
              {filtered.length} trajectories · content hashes retained in
              manifest
            </div>
          </Panel>
        </>
      )}
    </>
  );
}
export function Lineage({ campaign }: { campaign: Campaign }) {
  const nodes = [
    { label: "Source failure", id: campaign.counterexample?.source_episode_id },
    {
      label: "Reduced scene",
      id: campaign.counterexample?.minimized_episode_id,
    },
    { label: "Curriculum", id: campaign.curriculum?.id },
    {
      label: "Learned checkpoint",
      id:
        str(
          record(
            campaign.report?.arms?.find(
              (a) => a.name === campaign.report?.selected_arm,
            )?.nomination,
          ).checkpoint_sha,
          "",
        ) || campaign.training?.runs?.[0]?.checkpoint_sha,
    },
    { label: "Evaluation", id: campaign.report?.id },
  ];
  return (
    <Panel className="lineage-panel">
      <SectionTitle
        eyebrow="CONTENT-ADDRESSED EVIDENCE"
        title="An unbroken chain of custody"
      />
      <ol className="lineage-chain">
        {nodes.map((node, i) => (
          <li key={node.label} className={node.id ? "available" : "pending"}>
            <span className="lineage-top">
              <span className="lineage-node">
                {node.id ? <Check size={11} /> : String(i + 1).padStart(2, "0")}
              </span>
              <span className="lineage-connector" />
            </span>
            <strong>{node.label}</strong>
            <span className="mono">
              {node.id ? shortHash(node.id) : "Not published"}
            </span>
          </li>
        ))}
      </ol>
    </Panel>
  );
}
export function Policies({
  campaign,
  bootstrap,
  camera,
  onCamera,
  onTrain,
  onEpisode,
  onChallenge,
  onParent,
}: {
  campaign: Campaign | null;
  bootstrap: Bootstrap | null;
  camera: string;
  onCamera: (v: string) => void;
  onTrain: () => void;
  onEpisode: (id: string) => void;
  onChallenge: (c: Campaign) => void;
  onParent: (id: string) => void;
}) {
  const [development, setDevelopment] = useState(false);
  const registered = !!campaign?.registered_report && !development;
  const report = registered ? campaign?.registered_report : campaign?.report;
  const [selectedArm, setSelectedArm] = useState("");
  const [regression, setRegression] = useState<Dict | null>(null);
  const arm =
    report?.arms?.find(
      (a) => a.name === (selectedArm || report.selected_arm),
    ) || report?.arms?.[0];
  const runs = campaign?.training?.runs || [];
  return (
    <>
      <PageHeading
        number="05"
        label="POLICY COMPARISON"
        title="Improvement earns its denominator."
        description="Compare real learned checkpoints against the frozen base. Rescued failures and new regressions stay in the same view."
        actions={
          report && campaign ? (
            <a
              className="button button-quiet"
              href={`/api/campaigns/${campaign.id}/export`}
              download
            >
              <Download size={16} />
              Export evidence
            </a>
          ) : (
            <button
              className="button button-primary"
              onClick={onTrain}
              disabled={
                !campaign?.curriculum || !!campaign.training?.runs?.length
              }
            >
              Review training
              <ArrowRight size={15} />
            </button>
          )
        }
      />
      {!campaign ? (
        <Empty title="No experiment selected">
          Choose a campaign to inspect learned policy evidence.
        </Empty>
      ) : campaign.challenge ||
        campaign.kind === "challenge" ||
        campaign.config.kind === "challenge" ? (
        <ChallengeOutcome
          campaign={campaign}
          camera={camera}
          onCamera={onCamera}
          onParent={onParent}
        />
      ) : !report ? (
        <>
          <Panel className="policy-pending">
            <div className="policy-pending-icon">
              <GraduationCap size={30} />
            </div>
            <Eyebrow>THE NEXT CLAIM REQUIRES A REAL CHECKPOINT</Eyebrow>
            <h2>
              {campaign.training
                ? "Training is in progress."
                : "The comparison follows training."}
            </h2>
            <p>
              {campaign.training
                ? "Optimizer updates, checkpoint hashes, and measured evaluation outcomes will appear as they are published."
                : "Review the validated curriculum, then train all registered arms from the same initialization."}
            </p>
            <Status value={campaign.training?.status ?? campaign.stage} />
          </Panel>
          {runs.length ? <TrainingLedger runs={runs} /> : null}
          <Lineage campaign={campaign} />
        </>
      ) : (
        <>
          {campaign.registered_report ? (
            <div
              className="evaluation-switch"
              role="group"
              aria-label="Evaluation evidence"
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
          <div className="evaluation-label">
            <ShieldCheck size={16} />
            <span>{report.label}</span>
            <span className="evaluation-scope">SIMULATION ONLY</span>
          </div>
          <div className="arm-tabs" role="group" aria-label="Select policy arm">
            {report.arms.map((a) => (
              <button
                key={a.name}
                aria-pressed={arm?.name === a.name}
                className={arm?.name === a.name ? "selected" : ""}
                onClick={() => setSelectedArm(a.name)}
              >
                <GitBranch size={14} />
                {a.label}
              </button>
            ))}
          </div>
          {arm ? (
            <>
              <div className="policy-overview">
                <div className="policy-score baseline-score">
                  <Eyebrow>FROZEN BASE POLICY</Eyebrow>
                  <div>
                    <strong className="mono">
                      {percent(report.baseline.rate, 1)}
                    </strong>
                    <span>
                      {report.baseline.successes} / {report.baseline.total}{" "}
                      successes
                    </span>
                  </div>
                  <span className="policy-rule" />
                </div>
                <div className="policy-delta">
                  <ArrowRight size={23} />
                  <strong className="mono">
                    {arm.delta > 0 ? "+" : ""}
                    {fixed(arm.delta * 100, 1)}
                    <small> pp</small>
                  </strong>
                  <span>observed difference</span>
                </div>
                <div className="policy-score revised-score">
                  <Eyebrow>{arm.label.toUpperCase()}</Eyebrow>
                  <div>
                    <strong className="mono">{percent(arm.rate, 1)}</strong>
                    <span>
                      {arm.successes} / {arm.total} successes
                    </span>
                  </div>
                  <span className="policy-rule" />
                </div>
              </div>
              <div className="uncertainty-line">
                <span>
                  {arm.interval == null ? (
                    "Pooled rate: descriptive across registered strata."
                  ) : (
                    <>
                      Reported 95% success interval{" "}
                      <strong className="mono">
                        {intervalText(arm.interval)}
                      </strong>
                    </>
                  )}
                </span>
                <span>
                  {arm.delta_interval == null ? (
                    "Per-stratum uncertainty is reported separately below."
                  ) : (
                    <>
                      Paired difference interval{" "}
                      <strong className="mono">
                        {differenceIntervalText(arm.delta_interval)}
                      </strong>
                    </>
                  )}
                </span>
              </div>
              <div className="comparison-method">
                <p>
                  {arm.total} policy executions
                  {arm.seeds?.length
                    ? ` across ${arm.seeds.length} checkpoint seeds on the same registered scenario manifest`
                    : " on the registered scenario manifest"}
                  .
                </p>
                {arm.interval_method ? <p>{str(arm.interval_method)}</p> : null}
                {arm.delta_interval_method ? (
                  <p>{str(arm.delta_interval_method)}</p>
                ) : null}
              </div>
              {registered && (arm.nominal || arm.shifted) ? (
                <Panel className="strata-panel">
                  <SectionTitle
                    eyebrow="SEPARATE REGISTERED STRATA"
                    title="Each distribution keeps its uncertainty."
                    detail="The pooled rate describes the fixed test composition. Nominal and shifted draws retain separate denominators and intervals."
                  />
                  <StratumTable arm={arm} />
                </Panel>
              ) : null}
              <div className="comparison-grid">
                <Panel className="paired-panel">
                  <SectionTitle
                    eyebrow="EVERY PAIRED OUTCOME"
                    title="What changed, exactly?"
                    detail="Same scenario and nuisance seed. Baseline and revised verdicts are paired."
                  />
                  <PairedOutcomes arm={arm} />
                </Panel>
                <Panel className="decision-panel">
                  <SectionTitle
                    eyebrow="MEASURED RELEASE GATE"
                    title={human(report.decision)}
                  />
                  <Status value={report.decision} />
                  <ul className="decision-reasons">
                    {report.decision_reasons?.map((reason, i) => (
                      <li key={i}>
                        <span>+</span>
                        {reason}
                      </li>
                    ))}
                  </ul>
                  <div className="decision-boundary">
                    <LockKeyhole size={18} />
                    <p>
                      {registered
                        ? "This registered simulation confirmation uses frozen checkpoints. Hardware qualification remains outside this report."
                        : "Exploratory development evidence cannot qualify promotion. Registered confirmation remains a separate review."}
                    </p>
                  </div>
                </Panel>
              </div>
              {arm.families?.length ? (
                <Panel className="family-panel">
                  <SectionTitle
                    eyebrow="DISTRIBUTION BREAKDOWN"
                    title="Performance by scenario family"
                    detail={
                      record(arm.nomination).seed != null
                        ? `Nominated checkpoint · training seed ${str(record(arm.nomination).seed)}. Family counts below describe this checkpoint.`
                        : undefined
                    }
                  />
                  <div className="table-scroll" tabIndex={0}>
                    <table>
                      <caption className="sr-only">
                        Measured outcomes per scenario family
                      </caption>
                      <thead>
                        <tr>
                          <th>Family</th>
                          <th>Successes / total</th>
                          <th>Rate</th>
                          <th>Recorded evidence</th>
                        </tr>
                      </thead>
                      <tbody>
                        {arm.families.map((family, i) => (
                          <tr key={i}>
                            <th>{human(family.family ?? family.name)}</th>
                            <td className="mono">
                              {str(family.successes)} / {str(family.total)}
                            </td>
                            <td className="mono">{percent(family.rate, 1)}</td>
                            <td>
                              {family.interval
                                ? intervalText(family.interval)
                                : "Per registered evaluation"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Panel>
              ) : null}
              <Panel className="regressions-panel">
                <SectionTitle
                  eyebrow="BEHAVIOR THAT GOT WORSE"
                  title="Regressions stay visible."
                  detail={
                    registered
                      ? `${report.regressions?.length ?? 0} regression replays for nominated checkpoints. The matrix above retains all training seeds.`
                      : `${report.regressions?.length ?? 0} recorded regression cases across the evaluated arms.`
                  }
                />
                {registered ? (
                  <RemainingFailures
                    report={report}
                    arm={arm}
                    onEpisode={onEpisode}
                  />
                ) : null}
                {report.regressions?.length ? (
                  <div className="regression-list">
                    {report.regressions.map((r, i) => (
                      <div key={i}>
                        <span className="regression-icon">
                          <TriangleAlert size={17} />
                        </span>
                        <div>
                          <strong>
                            {human(
                              r.family ??
                                record(r.scenario).family ??
                                r.arm ??
                                "Regression",
                            )}
                          </strong>
                          <span className="mono">
                            {str(r.base_episode_id).slice(-12)} →{" "}
                            {str(r.revised_episode_id).slice(-12)}
                          </span>
                        </div>
                        <button
                          className="text-button"
                          onClick={() => setRegression(r)}
                        >
                          Compare replay
                          <ArrowUpRight size={14} />
                        </button>
                        <button
                          className="icon-button"
                          aria-label={`Inspect revised regression episode ${str(r.revised_episode_id)}`}
                          onClick={() => onEpisode(str(r.revised_episode_id))}
                        >
                          <FileCode2 size={16} />
                        </button>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="no-regressions">
                    <Check size={17} />
                    <span>
                      {registered
                        ? "No new regression replays are listed for the nominated checkpoints. Other training seeds retain their own outcomes in the aggregate matrix."
                        : "No paired regression cases are listed in this development report. Inspect the seed outcomes and evaluated denominators above."}
                    </span>
                  </div>
                )}
              </Panel>
            </>
          ) : null}
          <SupplementaryReproductions campaign={campaign} />
          <ChallengeForm
            campaign={campaign}
            bootstrap={bootstrap}
            onCreated={onChallenge}
          />
          <TrainingLedger runs={runs} />
          <Lineage campaign={campaign} />
          {regression ? (
            <Drawer
              title="Paired regression replay"
              eyebrow="BASE SUCCESS → REVISED FAILURE"
              onClose={() => setRegression(null)}
              wide
            >
              <p className="drawer-intro">
                The same registered scenario and seed, compared in simulation
                seconds.
              </p>
              <ReplayPair
                campaign={campaign}
                camera={camera}
                onCamera={onCamera}
                leftId={str(regression.base_episode_id, "")}
                rightId={str(regression.revised_episode_id, "")}
                leftLabel="Frozen base policy"
                rightLabel="Revised policy"
                compact
              />
              <JsonDetails
                value={regression}
                label="Regression case manifest"
              />
            </Drawer>
          ) : null}
        </>
      )}
    </>
  );
}
function PairedOutcomes({ arm }: { arm: ReportArm }) {
  const p = arm.paired;
  if (!p)
    return (
      <Empty title="Paired outcomes pending">
        The engine will publish the actual scenario-paired verdicts.
      </Empty>
    );
  return (
    <div className="paired-outcomes">
      <div className="paired-axis-label">REVISED POLICY</div>
      <table>
        <caption className="sr-only">
          Paired outcome matrix for {arm.label}
        </caption>
        <thead>
          <tr>
            <th>Frozen base</th>
            <th>Success</th>
            <th>Failure</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <th>Success</th>
            <td className="paired-unchanged">
              <strong className="mono">{p.both_success}</strong>
              <span>Unchanged successes</span>
            </td>
            <td className="paired-regressed">
              <strong className="mono">{p.regressed}</strong>
              <span>New regressions</span>
            </td>
          </tr>
          <tr>
            <th>Failure</th>
            <td className="paired-rescued">
              <strong className="mono">{p.rescued}</strong>
              <span>Rescued failures</span>
            </td>
            <td className="paired-unchanged">
              <strong className="mono">{p.both_failure}</strong>
              <span>Unchanged failures</span>
            </td>
          </tr>
        </tbody>
      </table>
      <p className="chart-footnote">
        Total paired outcomes:{" "}
        {p.both_success + p.regressed + p.rescued + p.both_failure}. Counts are
        reported by the evaluation engine.
        {arm.seeds?.length
          ? ` Shared scenario manifest across ${arm.seeds.length} trained checkpoints.`
          : ""}
      </p>
    </div>
  );
}
function TrainingLedger({ runs }: { runs: TrainingRun[] }) {
  return (
    <Panel className="training-ledger">
      <SectionTitle
        eyebrow="ACTUAL OPTIMIZER UPDATES"
        title="The checkpoint ledger"
        detail="Loss endpoints and weight changes are measured from each training run."
      />
      {runs.length ? (
        <div className="table-scroll" tabIndex={0}>
          <table>
            <caption className="sr-only">
              Training runs, seeds, real loss endpoints, and checkpoint hashes
            </caption>
            <thead>
              <tr>
                <th>Arm</th>
                <th>Seed</th>
                <th>Examples / steps</th>
                <th>Initial → final loss</th>
                <th>Weight change L2</th>
                <th>Checkpoint</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r, i) => (
                <tr key={i}>
                  <th>{human(r.arm)}</th>
                  <td className="mono">{r.seed}</td>
                  <td className="mono">
                    {r.examples} / {r.steps}
                  </td>
                  <td className="mono">
                    {fixed(r.initial_loss, 5)} <span className="muted">→</span>{" "}
                    {fixed(r.final_loss, 5)}
                  </td>
                  <td className="mono">{fixed(r.weight_change_l2, 4)}</td>
                  <td className="mono">{shortHash(r.checkpoint_sha)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Empty title="No learned checkpoints yet">
          A completed optimizer run is required before this table reports a
          policy revision.
        </Empty>
      )}
    </Panel>
  );
}

function clusterLabel(value: unknown, index: number) {
  const r = record(value);
  return human(
    typeof value === "string"
      ? value
      : (r.label ??
          r.terminal_reason ??
          r.reason ??
          r.name ??
          `Cluster ${index + 1}`),
  );
}
function allocationEntries(
  value: unknown,
  clusters: unknown[],
): [string, React.ReactNode][] {
  if (Array.isArray(value))
    return value.map((n, i) => [
      `${clusterLabel(clusters[i], i)} corrections`,
      String(n),
    ]);
  return Object.entries(record(value)).map(([k, v]) => [
    `${human(k)} corrections`,
    String(v),
  ]);
}

export function StratumTable({ arm }: { arm: ReportArm }) {
  const rows = [
    { label: "Nominal", value: arm.nominal },
    { label: "Shifted", value: arm.shifted },
  ].filter((r) => r.value);
  return (
    <>
      <div className="table-scroll" tabIndex={0}>
        <table>
          <caption className="sr-only">
            Separate registered evaluation strata and reported uncertainty
          </caption>
          <thead>
            <tr>
              <th>Stratum</th>
              <th>Successes / executions</th>
              <th>Rate</th>
              <th>95% success interval</th>
              <th>Paired difference interval</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const r = record(row.value);
              return (
                <tr key={row.label}>
                  <th>{row.label}</th>
                  <td className="mono">
                    {str(r.successes)} / {str(r.total)}
                  </td>
                  <td className="mono">{percent(r.rate, 1)}</td>
                  <td className="mono">
                    {r.interval == null
                      ? "Descriptive"
                      : intervalText(r.interval)}
                  </td>
                  <td className="mono">
                    {r.delta_interval == null
                      ? "Descriptive"
                      : differenceIntervalText(r.delta_interval)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <JsonDetails
        value={Object.fromEntries(
          rows.map((row) => {
            const r = record(row.value);
            return [
              row.label,
              {
                interval_method: r.interval_method,
                delta_interval_method: r.delta_interval_method,
                nominal_lower_95: r.nominal_lower_95,
                scheduled: r.scheduled,
                invalid: r.invalid,
                paired: r.paired,
              },
            ];
          }),
        )}
        label="Within-stratum methods and paired outcomes"
      />
    </>
  );
}
