import { useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  Check,
  ChevronRight,
  FlaskConical,
  Focus,
  Layers3,
  ShieldCheck,
  Sparkles,
  Target,
  X,
} from "lucide-react";
import { useEpisode } from "./api";
import {
  array,
  episodeVerdict,
  fixed,
  formatValue,
  human,
  intervalText,
  num,
  record,
  str,
} from "./data";
import { ReplayPair } from "./Replay";
import {
  ActionLink,
  DataDetails,
  DefinitionList,
  Drawer,
  Empty,
  Eyebrow,
  JsonDetails,
  PageHeading,
  Panel,
  SectionTitle,
  StageCheck,
  Status,
} from "./ui";
import type { Campaign, Counterexample, ReductionStep, View } from "./types";

export function Workcell({
  campaign: sourceCampaign,
  camera,
  onCamera,
  navigate,
  onLaunch,
  onEpisode,
  onTask,
  baseReady,
  connecting,
  boundary,
  onBoundary,
}: {
  campaign: Campaign | null;
  camera: string;
  onCamera: (v: string) => void;
  navigate: (view: View) => void;
  onLaunch: () => void;
  onEpisode: (id: string) => void;
  onTask: () => void;
  baseReady: boolean;
  connecting: boolean;
  boundary: string;
  onBoundary: (index: number) => void;
}) {
  const boundaries = sourceCampaign?.counterexample
    ? [
        sourceCampaign.counterexample,
        ...(sourceCampaign.counterexample.secondary_boundaries || []),
      ]
    : [];
  const selectedBoundary = Math.max(
    0,
    Math.min(Number(boundary) || 0, boundaries.length - 1),
  );
  const campaign = sourceCampaign
    ? {
        ...sourceCampaign,
        counterexample:
          boundaries[selectedBoundary] || sourceCampaign.counterexample,
      }
    : null;
  return (
    <>
      <PageHeading
        number="01"
        label="PHYSICAL AI RELIABILITY"
        title="Find the failure. Forge the fix."
        description="Turn a physical failure into a smaller counterexample, a corrective curriculum, and a measured policy decision."
        actions={
          <>
            <button className="button button-quiet" onClick={onLaunch}>
              <FlaskConical size={16} />
              Start a campaign
            </button>
            <button
              className="button button-primary"
              onClick={() => navigate("failures")}
              disabled={!campaign?.counterexample}
            >
              <Focus size={16} />
              Inspect failure
              <ArrowUpRight size={15} />
            </button>
          </>
        }
      />
      <div className="task-ribbon">
        <div className="task-ribbon-icon">
          <Layers3 size={20} />
        </div>
        <div>
          <strong>Cartesian kit transfer</strong>
          <span>
            3-axis gantry · parallel jaws · protected neighboring object
          </span>
        </div>
        <div className="ribbon-label">
          <span className="tiny-cross">+</span>LOCAL SIMULATION
        </div>
        <button className="text-button" onClick={onTask}>
          Task specification
          <ArrowUpRight size={14} />
        </button>
      </div>
      {campaign ? (
        <>
          <BoundaryTabs
            boundaries={boundaries}
            selected={selectedBoundary}
            onChange={onBoundary}
          />
          <div className="workcell-composition workcell-home">
            <div className="microscope-main">
              <ReplayPair
                campaign={campaign}
                camera={camera}
                onCamera={onCamera}
              />
            </div>
            <EvidenceRail
              campaign={campaign}
              onCurriculum={() => navigate("curricula")}
              onEpisode={onEpisode}
            />
            <div className="workcell-lower">
              <Panel className="reduction-overview">
                <SectionTitle
                  eyebrow="LESS VARIATION. SAME OBSERVED FAILURE."
                  title="Isolate what matters."
                >
                  <ActionLink onClick={() => navigate("failures")}>
                    Open reduction
                  </ActionLink>
                </SectionTitle>
                <ReductionSummary campaign={campaign} />
                <div className="parameter-mini-list">
                  {Object.keys(
                    campaign.counterexample?.source_params || {},
                  ).map((key) => (
                    <div key={key}>
                      <span>{human(key)}</span>
                      <span className="mono source-text">
                        {parameterValue(
                          key,
                          campaign.counterexample?.source_params[key],
                        )}
                      </span>
                      <ArrowRight size={13} />
                      <span className="mono">
                        {parameterValue(
                          key,
                          campaign.counterexample?.minimized_params[key],
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              </Panel>
              <Panel className="loop-panel">
                <SectionTitle
                  eyebrow="ONE INSPECTABLE CHAIN"
                  title="Evidence becomes the next experiment."
                />
                <CampaignStages campaign={campaign} />
                <div className="loop-footnote">
                  <ShieldCheck size={17} />
                  <p>
                    The physics oracle owns the verdict. Model explanations
                    remain hypotheses.
                  </p>
                </div>
              </Panel>
            </div>
          </div>
        </>
      ) : (
        <div className="empty-instrument">
          <div className="empty-instrument-grid" />
          <Empty
            title={
              connecting
                ? "Connecting to the local runtime"
                : baseReady
                  ? "Your first experiment starts here."
                  : "The local checkpoint is not prepared."
            }
            action={
              baseReady ? (
                <button className="button button-primary" onClick={onLaunch}>
                  <FlaskConical size={15} />
                  Start a campaign
                  <ArrowRight size={14} />
                </button>
              ) : !connecting ? (
                <button className="text-button" onClick={onTask}>
                  Inspect local setup
                  <ArrowUpRight size={13} />
                </button>
              ) : undefined
            }
          >
            {connecting ? (
              "The interface is requesting the registered task and any recorded campaign evidence."
            ) : baseReady ? (
              "No campaign evidence has been recorded yet. Start a bounded experiment to discover a physical failure, reduce it, and acquire corrective demonstrations."
            ) : (
              <>
                Prepare the base checkpoint locally with{" "}
                <code>python scripts/bootstrap.py</code>. Launch becomes
                available when its validated artifact is ready.
              </>
            )}
          </Empty>
        </div>
      )}
    </>
  );
}
export function EvidenceRail({
  campaign,
  onCurriculum,
  onEpisode,
}: {
  campaign: Campaign;
  onCurriculum: () => void;
  onEpisode: (id: string) => void;
}) {
  const [modelOpen, setModelOpen] = useState(false);
  const counter = campaign.counterexample;
  const { episode } = useEpisode(
    counter?.minimized_episode_id || counter?.source_episode_id,
  );
  const metrics = episode?.metrics || {};
  const planner = campaign.model_evidence?.planner;
  const visual = campaign.model_evidence?.visual;
  const content = record(planner?.content);
  const hypotheses = array(planner?.hypotheses ?? content.hypotheses);
  const focusFactor = counter?.steps
    ?.filter((step) => step.accepted)
    .at(-1)?.factor;
  const matched = focusFactor
    ? hypotheses.find(
        (h) =>
          record(h).factor === focusFactor ||
          array(record(h).factors).includes(focusFactor),
      )
    : undefined;
  const selectedHypothesis = matched ?? hypotheses[0];
  const first = record(selectedHypothesis);
  const hypothesis =
    typeof selectedHypothesis === "string"
      ? selectedHypothesis
      : str(
          first.claim ??
            first.hypothesis ??
            first.description ??
            first.mechanism ??
            first.rationale ??
            first.summary,
          str(
            planner?.summary,
            "The planner's bounded search evidence will appear after its recorded response is validated.",
          ),
        );
  const forbidden =
    metrics.forbidden_contact_steps ??
    metrics.forbidden_contact_count ??
    metrics.forbidden_contacts;
  const displacement =
    metrics.protected_max_displacement ??
    metrics.max_protected_displacement ??
    metrics.protected_displacement_max ??
    metrics.protected_displacement;
  const reason =
    episode?.terminal_reason ?? record(episode?.outcome).terminal_reason;
  return (
    <aside className="evidence-rail" aria-label="Failure evidence">
      <div className="evidence-rail-heading">
        <Eyebrow>OBSERVATION / INTERPRETATION</Eyebrow>
        <h2>Follow the evidence.</h2>
        <div className="source-mode">
          {campaign.recorded ? (
            <span className="recording-square" />
          ) : (
            <span className="status-dot" />
          )}
          {campaign.recorded ? "Recorded campaign" : "Live campaign"}
          <span className="mono">{campaign.id.slice(-8)}</span>
        </div>
      </div>
      <section className="evidence-block measured-block">
        <div className="evidence-type">
          <span>
            <Target size={13} />
            MEASURED
          </span>
          <span className="evidence-source">PHYSICS ORACLE</span>
        </div>
        <h3>
          {episode
            ? human(reason ?? episodeVerdict(episode))
            : "Verifying the counterexample"}
        </h3>
        {episode ? (
          <p>
            The terminal verdict is computed from contacts, geometry, and the
            registered task predicate.
          </p>
        ) : (
          <p>Awaiting the authoritative episode and confirmation draws.</p>
        )}
        <DefinitionList
          entries={[
            [
              "Fresh confirmation",
              counter
                ? `${counter.confirmation?.failures ?? "—"} / ${counter.confirmation?.total ?? "—"} failures`
                : "Pending",
            ],
            [
              "95% failure interval",
              counter?.confirmation?.interval
                ? intervalText(counter.confirmation.interval)
                : "Pending",
            ],
            ...(displacement != null
              ? [
                  [
                    "Maximum protected drift",
                    `${fixed(num(displacement) * 1000, 2)} mm`,
                  ] as [string, string],
                ]
              : []),
            ...(forbidden != null
              ? [
                  ["Forbidden-contact steps", formatValue(forbidden)] as [
                    string,
                    string,
                  ],
                ]
              : []),
          ]}
        />
        {episode ? (
          <ActionLink
            onClick={() =>
              onEpisode(
                counter?.minimized_episode_id ||
                  counter?.source_episode_id ||
                  "",
              )
            }
          >
            Inspect oracle evidence
          </ActionLink>
        ) : null}
      </section>
      <section className="evidence-block hypothesis-block">
        <div className="evidence-type">
          <span>
            <Sparkles size={13} />
            {matched ? "NVIDIA HYPOTHESIS" : "CAMPAIGN-WIDE HYPOTHESIS"}
          </span>
          <span className="hypothesis-symbol">?</span>
        </div>
        <h3>
          {str(
            first.title,
            first.factor ? human(first.factor) : "A testable explanation.",
          )}
        </h3>
        <p>
          {hypothesis.length > 270
            ? `${hypothesis.slice(0, 267)}…`
            : hypothesis}
        </p>
        <div className="model-attribution">
          <span className="model-mini-mark">N</span>
          <div>
            <strong>{str(planner?.provider, "Planner pending")}</strong>
            <span>
              {str(planner?.model, "Model identity follows the receipt")}
            </span>
          </div>
        </div>
        <button className="text-button" onClick={() => setModelOpen(true)}>
          Model evidence
          <ArrowUpRight size={13} />
        </button>
      </section>
      <div className="evidence-next">
        <span className="next-label">NEXT INVESTIGATION</span>
        <button onClick={onCurriculum}>
          <span>Review the corrective curriculum</span>
          <ArrowRight size={20} />
        </button>
        <p>
          {campaign.curriculum
            ? `${campaign.curriculum.demonstrations?.filter((d) => d.success).length ?? 0} validated demonstrations · inspect provenance`
            : "The worker acquires successful demonstrations after reduction."}
        </p>
      </div>
      {modelOpen ? (
        <Drawer
          title="Model evidence and provenance"
          eyebrow="ADVISORY NVIDIA REASONING"
          onClose={() => setModelOpen(false)}
        >
          <p className="drawer-intro">
            The model proposes and interprets bounded experiments. It cannot
            change the task predicate, overwrite measurements, or approve a
            policy.
          </p>
          <h3>Search planner</h3>
          <DataDetails value={planner} />
          <h3 className="spaced-heading">Visual interpretation</h3>
          <DataDetails value={visual} />
        </Drawer>
      ) : null}
    </aside>
  );
}
export function parameterValue(key: string, value: unknown) {
  if (typeof value !== "number") return formatValue(value);
  if (/height|offset|clearance/.test(key))
    return `${fixed(value * 1000, 1)} mm`;
  if (/yaw|angle/.test(key)) return `${fixed((value * 180) / Math.PI, 1)}°`;
  return fixed(value, 3);
}
export function ReductionSummary({ campaign }: { campaign: Campaign }) {
  const c = campaign.counterexample;
  return c ? (
    <div className="reduction-summary">
      <div>
        <span className="big-number mono source-text">{c.changed_before}</span>
        <span>changed factors</span>
      </div>
      <span className="reduction-arrow">
        <ArrowRight size={25} />
      </span>
      <div>
        <span className="big-number mono">{c.changed_after}</span>
        <span>in the counterexample</span>
      </div>
      <div className="reduction-confirm">
        <span className="mono">
          {c.confirmation?.failures} / {c.confirmation?.total}
        </span>
        <span>fresh replay failures</span>
      </div>
    </div>
  ) : (
    <Empty title="Reduction is pending">
      The source failure must be established before a parameter can be removed.
    </Empty>
  );
}
export function CampaignStages({ campaign }: { campaign: Campaign }) {
  const stages = [
    { label: "Discover", stage: "discovery", done: !!campaign.counterexample },
    { label: "Reduce", stage: "minimization", done: !!campaign.counterexample },
    { label: "Acquire", stage: "curriculum", done: !!campaign.curriculum },
    {
      label: "Train",
      stage: "training",
      done:
        !!campaign.training?.runs?.length &&
        campaign.training.status === "completed",
    },
    { label: "Evaluate", stage: "evaluation", done: !!campaign.report },
  ];
  return (
    <div className="campaign-stages">
      {stages.map((s, i) => (
        <StageCheck
          key={s.label}
          label={s.label}
          number={i + 1}
          state={
            s.done
              ? "done"
              : campaign.stage?.includes(s.stage)
                ? "current"
                : "pending"
          }
        />
      ))}
    </div>
  );
}
export function Failures({
  campaign: sourceCampaign,
  camera,
  onCamera,
  onEpisode,
  onCurriculum,
  boundary,
  onBoundary,
}: {
  campaign: Campaign | null;
  camera: string;
  onCamera: (s: string) => void;
  onEpisode: (id: string) => void;
  onCurriculum: () => void;
  boundary: string;
  onBoundary: (index: number) => void;
}) {
  const boundaries = sourceCampaign?.counterexample
    ? [
        sourceCampaign.counterexample,
        ...(sourceCampaign.counterexample.secondary_boundaries || []),
      ]
    : [];
  const selectedBoundary = Math.max(
    0,
    Math.min(Number(boundary) || 0, boundaries.length - 1),
  );
  const campaign = sourceCampaign
    ? {
        ...sourceCampaign,
        counterexample:
          boundaries[selectedBoundary] || sourceCampaign.counterexample,
      }
    : null;
  const [selectedStep, setSelectedStep] = useState<number | null>(null);
  const [showAll, setShowAll] = useState(false);
  const c = campaign?.counterexample;
  const steps = c?.steps || [];
  const visible = showAll ? steps : steps.slice(0, 7);
  const current = selectedStep == null ? null : steps[selectedStep];
  return (
    <>
      <PageHeading
        number="03"
        label="COUNTEREXAMPLE ANALYSIS"
        title="A smaller scene. A sharper question."
        description="Synchronized physical replays preserve the observed failure while tested reductions remove unnecessary variation."
        actions={
          <button
            className="button button-primary"
            disabled={!campaign?.curriculum}
            onClick={onCurriculum}
          >
            Review corrective curriculum
            <ArrowRight size={16} />
          </button>
        }
      />
      {!campaign ? (
        <Empty title="No campaign selected">
          Choose a campaign to inspect its failure evidence.
        </Empty>
      ) : (
        <>
          <BoundaryTabs
            boundaries={boundaries}
            selected={selectedBoundary}
            onChange={(index) => {
              onBoundary(index);
              setSelectedStep(null);
              setShowAll(false);
            }}
          />
          <div className="failure-headline">
            <div>
              <Eyebrow>REPLAY-BASED REDUCTION</Eyebrow>
              <ReductionSummary campaign={campaign} />
            </div>
            <div className="failure-scope">
              <Status
                value={c ? "completed" : "pending"}
                label={
                  c ? "Finite neighborhood tested" : "Awaiting counterexample"
                }
              />
              <p>
                {c
                  ? localityText(c.locality)
                  : "No local-minimality claim is made until the registered replay neighborhood is tested."}
              </p>
            </div>
          </div>
          <div className="workcell-composition">
            <ReplayPair
              campaign={campaign}
              camera={camera}
              onCamera={onCamera}
              rightId={current?.episode_ids?.[0]}
              rightLabel={
                current ? `Tested: ${human(current.factor)}` : undefined
              }
            />
            <EvidenceRail
              campaign={campaign}
              onCurriculum={onCurriculum}
              onEpisode={onEpisode}
            />
          </div>
          <div className="failure-detail-grid">
            <Panel className="ladder-panel">
              <SectionTitle
                eyebrow="EVERY PROPOSAL RETAINED"
                title="The parameter ladder"
                detail="Select a reduction to inspect its paired replay evidence."
              />
              <div className="parameter-ladder">
                {visible.length ? (
                  visible.map((step, i) => (
                    <ReductionRow
                      key={`${step.factor}-${i}`}
                      step={step}
                      index={i}
                      selected={selectedStep === i}
                      onClick={() =>
                        setSelectedStep(selectedStep === i ? null : i)
                      }
                      onEpisode={onEpisode}
                    />
                  ))
                ) : (
                  <Empty title="No reduction trials yet">
                    The worker logs accepted and rejected proposals here.
                  </Empty>
                )}
              </div>
              {steps.length > 7 ? (
                <button
                  className="text-button"
                  onClick={() => setShowAll((v) => !v)}
                >
                  {showAll
                    ? "Show fewer trials"
                    : `Show all ${steps.length} trials`}
                  <ArrowDown size={14} />
                </button>
              ) : null}
            </Panel>
            <Panel className="reduction-notebook">
              <SectionTitle
                eyebrow="METHOD / BOUNDED CLAIM"
                title="What the evidence establishes"
              />
              <div className="notebook-item">
                <span>01</span>
                <div>
                  <h3>Paired nuisance draws</h3>
                  <p>
                    Each proposed reduction is compared under the registered
                    nuisance-seed distribution. Rejected reductions remain
                    visible.
                  </p>
                </div>
              </div>
              <div className="notebook-item">
                <span>02</span>
                <div>
                  <h3>Fresh confirmation</h3>
                  <p>
                    {c
                      ? `${c.confirmation?.failures} failures across ${c.confirmation?.total} new draws. ${c.confirmation?.interval ? `95% interval ${intervalText(c.confirmation.interval)}.` : ""}`
                      : "Fresh confirmation begins after a stable counterexample is found."}
                  </p>
                </div>
              </div>
              <div className="notebook-item">
                <span>03</span>
                <div>
                  <h3>Local, finite, explicit</h3>
                  <p>
                    {c
                      ? localityText(c.locality)
                      : "The registered neighborhood includes reversals and nonadjacent grid substitutions; failure monotonicity is not assumed."}
                  </p>
                </div>
              </div>
              {c ? (
                <JsonDetails value={c} label="Complete reduction manifest" />
              ) : null}
            </Panel>
          </div>
        </>
      )}
    </>
  );
}
function ReductionRow({
  step,
  index,
  selected,
  onClick,
  onEpisode,
}: {
  step: ReductionStep;
  index: number;
  selected: boolean;
  onClick: () => void;
  onEpisode: (id: string) => void;
}) {
  return (
    <div className={`ladder-row ${selected ? "selected" : ""}`}>
      <button
        className="ladder-select"
        aria-pressed={selected}
        onClick={onClick}
      >
        <span className="ladder-number mono">
          {String(index + 1).padStart(2, "0")}
        </span>
        <span
          className={`ladder-verdict ${step.accepted ? "accepted" : "reverted"}`}
        >
          {step.accepted ? <Check size={13} /> : <X size={13} />}
        </span>
        <span className="ladder-factor">
          <strong>{human(step.factor)}</strong>
          <span className="mono">
            {parameterValue(step.factor, step.from_value)}
            <ArrowRight size={11} />
            {parameterValue(step.factor, step.to_value)}
          </span>
        </span>
        <span className="ladder-result">
          <span>
            {step.failure_count} / {step.valid_count}
          </span>
          <small>{step.accepted ? "retained" : "reverted"}</small>
        </span>
        <ChevronRight size={14} />
      </button>
      {selected ? (
        <div className="ladder-expanded">
          <p>
            {human(step.kind)} · {step.valid_count} valid physical replays ·{" "}
            {step.failure_count} measured failures
          </p>
          <div>
            {step.episode_ids?.map((id) => (
              <button
                className="evidence-chip mono"
                key={id}
                onClick={() => onEpisode(id)}
              >
                {id.slice(-10)}
                <ArrowUpRight size={11} />
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

function localityText(value: unknown) {
  if (typeof value === "string") return value;
  const r = record(value);
  return str(
    r.neighborhood,
    str(r.reason, "The registered finite reduction neighborhood."),
  );
}

function BoundaryTabs({
  boundaries,
  selected,
  onChange,
}: {
  boundaries: Counterexample[];
  selected: number;
  onChange: (i: number) => void;
}) {
  if (boundaries.length < 2) return null;
  return (
    <div
      className="boundary-tabs"
      role="group"
      aria-label="Select measured failure boundary"
    >
      <span>{boundaries.length} MEASURED BOUNDARIES</span>
      {boundaries.map((b, i) => (
        <button
          key={b.source_episode_id || i}
          className={i === selected ? "selected" : ""}
          aria-pressed={i === selected}
          onClick={() => onChange(i)}
        >
          <span className="mono">{String(i + 1).padStart(2, "0")}</span>
          {human(
            b.label ??
              record(b).terminal_reason ??
              b.failure_reason ??
              b.reason ??
              `Boundary ${i + 1}`,
          )}
          <small>
            {b.confirmation?.failures} / {b.confirmation?.total} failures
          </small>
        </button>
      ))}
    </div>
  );
}
