import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  GitBranch,
  LoaderCircle,
  Play,
  RotateCcw,
  Square,
  X,
} from "lucide-react";
import { actionKey, request } from "./api";
import {
  human,
  differenceIntervalText,
  num,
  record,
  shortHash,
  str,
} from "./data";
import { ReplayPair } from "./Replay";
import { IncidentPlannerEvidence } from "./IncidentPlannerEvidence";
import { IncidentExport } from "./IncidentExport";
import {
  Drawer,
  ErrorMessage,
  Eyebrow,
  JsonDetails,
  Loading,
  Status,
} from "./ui";
import type { Campaign, Dict } from "./types";

type Source = {
  source_episode_id: string;
  name?: string;
  scenario: Dict;
  terminal_reason: string;
  checkpoint_hash: string;
  policy_id: string;
  source_artifact_sha: string;
};
type Factor = {
  nominal: number;
  min: number;
  max: number;
  step: number;
  unit: string;
};
type IncidentContext = {
  campaign_id: string;
  factor_spec: Record<string, Factor>;
  sources: Source[];
  label: string;
  scope: string;
};
type Branch = {
  episode_url: string;
  success: boolean;
  terminal_reason: string;
  evidence_hash: string;
};
type Pair = {
  trial_index: number;
  seed: number;
  original: Branch;
  intervention: Branch;
  validity: Dict;
};
type IncidentJob = {
  id: string;
  status: string;
  config: Dict;
  progress: { completed: number; total: number; message: string };
  pairs: Pair[];
  validity: Dict;
  attempts: unknown[];
  summary?: Dict;
  error?: unknown;
  label: string;
  scope: string;
};
const running = (job: IncidentJob | null) =>
  !!job && ["queued", "running"].includes(job.status);
function valueText(key: string, value: unknown) {
  if (typeof value !== "number") return "—";
  if (/height|offset/.test(key)) return `${(value * 1000).toFixed(1)} mm`;
  if (/yaw/.test(key)) return `${((value * 180) / Math.PI).toFixed(1)}°`;
  return value.toFixed(3);
}
function parameters(source?: Source) {
  return record(source?.scenario.parameters ?? source?.scenario);
}

export function IncidentWorkbench({
  campaign,
  sourceId,
  onClose,
  camera,
  onCamera,
}: {
  campaign: Campaign;
  sourceId?: string;
  onClose: () => void;
  camera: string;
  onCamera: (v: string) => void;
}) {
  const [context, setContext] = useState<IncidentContext | null>(null);
  const [source, setSource] = useState(sourceId || "");
  const [factor, setFactor] = useState("obstacle_height");
  const [value, setValue] = useState(0.065);
  const [repeats, setRepeats] = useState(5);
  const [job, setJob] = useState<IncidentJob | null>(null);
  const [replayTrial, setReplayTrial] = useState(0);
  const [history, setHistory] = useState<IncidentJob[]>([]);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [pollRetry, setPollRetry] = useState(0);
  const key = useRef(actionKey("incident"));
  useEffect(() => {
    if (!job) return;
    setHistory((items) =>
      items.some((item) => item.id === job.id)
        ? items.map((item) => (item.id === job.id ? job : item))
        : [job, ...items],
    );
  }, [job]);
  useEffect(() => {
    const abort = new AbortController();
    request<IncidentContext>(
      `/incidents/context?campaign_id=${encodeURIComponent(campaign.id)}`,
      { signal: abort.signal },
    )
      .then((data) => {
        setContext(data);
        setSource(
          data.sources.some((s) => s.source_episode_id === sourceId)
            ? sourceId!
            : data.sources[0]?.source_episode_id || "",
        );
        setValue(data.factor_spec.obstacle_height?.nominal ?? 0.065);
      })
      .catch((err) => {
        if (!abort.signal.aborted) setError(err.message);
      });
    request<IncidentJob[] | { incidents: IncidentJob[] }>("/incidents", {
      signal: abort.signal,
    })
      .then((data) => {
        const list = Array.isArray(data) ? data : data.incidents || [];
        setHistory(
          list.filter((item) => item.config?.campaign_id === campaign.id),
        );
      })
      .catch(() => {});
    return () => abort.abort();
  }, [campaign.id, sourceId, retry]);
  useEffect(() => {
    if (!job || !running(job)) return;
    const abort = new AbortController();
    const timer = setTimeout(() => {
      request<IncidentJob>(`/incidents/${encodeURIComponent(job.id)}`, {
        signal: abort.signal,
      })
        .then((result) => {
          setJob(result);
          setError("");
        })
        .catch((err) => {
          if (!abort.signal.aborted) {
            setError(err.message);
            setPollRetry((v) => v + 1);
          }
        });
    }, 1000);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [job, pollRetry]);
  const selected = context?.sources.find((s) => s.source_episode_id === source);
  const f = context?.factor_spec[factor];
  const from = num(parameters(selected)[factor]);
  const busy = pending || running(job);
  const valid =
    !!selected &&
    !!f &&
    Number.isFinite(value) &&
    value >= f.min &&
    value <= f.max &&
    value !== from &&
    Number.isInteger(repeats) &&
    repeats >= 1 &&
    repeats <= 20;
  function changeFactor(next: string) {
    setFactor(next);
    setValue(context?.factor_spec[next]?.nominal ?? 0);
    key.current = actionKey("incident");
  }
  async function start() {
    if (!valid || busy) return;
    setPending(true);
    setError("");
    try {
      const result = await request<IncidentJob>("/incidents", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": key.current,
        },
        body: JSON.stringify({
          campaign_id: campaign.id,
          source_episode_id: source,
          factor,
          value,
          nuisance_repeats: repeats,
        }),
      });
      setJob(result);
      setReplayTrial(0);
      setHistory((items) => [
        result,
        ...items.filter((item) => item.id !== result.id),
      ]);
      key.current = actionKey("incident");
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "The paired experiment did not start.",
      );
    } finally {
      setPending(false);
    }
  }
  async function cancel() {
    if (!job) return;
    setPending(true);
    try {
      setJob(
        await request<IncidentJob>(
          `/incidents/${encodeURIComponent(job.id)}/cancel`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Idempotency-Key": actionKey("incident-cancel"),
            },
            body: "{}",
          },
        ),
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Cancellation was not confirmed.",
      );
    } finally {
      setPending(false);
    }
  }
  async function inspect(id: string) {
    setError("");
    try {
      const result = await request<IncidentJob>(
        `/incidents/${encodeURIComponent(id)}`,
      );
      setJob(result);
      setSource(str(result.config.source_episode_id));
      setFactor(str(result.config.factor));
      setValue(num(result.config.value));
      setRepeats(num(result.config.nuisance_repeats, 1));
      setReplayTrial(0);
      key.current = actionKey("incident");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Evidence is unavailable.");
    }
  }
  const pairs = job?.pairs || [];
  const anchor = pairs.find((pair) => pair.trial_index === 0);
  const replayPair =
    pairs.find((pair) => pair.trial_index === replayTrial) || anchor;
  const fresh = pairs.filter(
    (pair) => pair.trial_index !== 0 && pair.validity?.valid === true,
  );
  const sourcePasses = fresh.filter((pair) => pair.original.success).length;
  const interventionPasses = fresh.filter(
    (pair) => pair.intervention.success,
  ).length;
  const rescues = fresh.filter(
    (pair) => !pair.original.success && pair.intervention.success,
  ).length;
  const regressions = fresh.filter(
    (pair) => pair.original.success && !pair.intervention.success,
  ).length;
  const selectedMatchesJob =
    !!job &&
    job.config.source_episode_id === source &&
    job.config.factor === factor &&
    job.config.value === value;
  const completed = job?.status === "completed";
  const pairedEffect = record(job?.summary?.paired_effect);
  const assessment = str(job?.summary?.assessment, "inconclusive");
  const interrupted =
    !!job && ["canceled", "failed", "interrupted"].includes(job.status);
  const resultTitle =
    job?.status === "canceled"
      ? "Run canceled"
      : job?.status === "failed"
        ? "Run failed"
        : job?.status === "interrupted"
          ? "Run interrupted"
          : !completed
            ? "Awaiting measured outcomes"
            : job.validity?.valid !== true
              ? "Pairing checks did not pass"
              : assessment === "fewer_failures_under_tested_intervention"
                ? "Fewer failures under this intervention"
                : assessment === "more_failures_under_tested_intervention"
                  ? "More failures under this intervention"
                  : "Evidence is inconclusive";
  return (
    <Drawer
      title="Fork this failure"
      eyebrow="CONTROLLED INITIAL-SCENE EXPERIMENT"
      onClose={onClose}
      wide
    >
      <div className="fork-intro">
        <GitBranch size={25} />
        <div>
          <p>Change one scene factor. Test its total effect.</p>
          <span>
            Both branches restart from the initial scene. The policy, task,
            unchanged factors and paired nuisance draws stay bound. Relevant
            initial geometry changes with your intervention.
          </span>
        </div>
      </div>
      <div className="fork-scope">
        <span className="mono">DIAGNOSTIC ONLY</span>
        <p>
          New post-final simulation evidence. Excluded from the frozen release
          report and training. Height and friction affect physics and
          instrumented policy observations; this does not isolate perception.
        </p>
      </div>
      {error ? (
        <ErrorMessage
          error={error}
          retry={
            !context
              ? () => {
                  setError("");
                  setRetry((v) => v + 1);
                }
              : undefined
          }
        />
      ) : null}
      {!context && !error ? (
        <Loading label="Binding eligible development incidents" />
      ) : context?.sources.length ? (
        <>
          <div className="fork-form">
            <label className="fork-source-label">
              INCIDENT SOURCE
              <select
                aria-label="Incident source"
                value={source}
                disabled={busy}
                onChange={(e) => {
                  setSource(e.target.value);
                  key.current = actionKey("incident");
                }}
              >
                {context.sources.map((item) => (
                  <option
                    key={item.source_episode_id}
                    value={item.source_episode_id}
                  >
                    {item.name || human(item.terminal_reason)} ·{" "}
                    {item.source_episode_id.slice(-14)}
                  </option>
                ))}
              </select>
            </label>
            <div className="fork-controls-grid">
              <label>
                CHANGE ONE FACTOR
                <select
                  aria-label="Intervention factor"
                  value={factor}
                  disabled={busy}
                  onChange={(e) => changeFactor(e.target.value)}
                >
                  {Object.keys(context.factor_spec).map((name) => (
                    <option key={name} value={name}>
                      {human(name)}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                FRESH PAIRED DRAWS
                <select
                  aria-label="Fresh paired draws"
                  value={repeats}
                  disabled={busy}
                  onChange={(e) => {
                    setRepeats(Number(e.target.value));
                    key.current = actionKey("incident");
                  }}
                >
                  {[1, 5, 10, 20].map((n) => (
                    <option key={n} value={n}>
                      {n} + source-seed anchor
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="fork-value-heading">
              <span>
                Source{" "}
                <strong className="mono">{valueText(factor, from)}</strong>
              </span>
              <ArrowRight size={17} />
              <label htmlFor="fork-value">
                Intervention{" "}
                <strong className="mono">{valueText(factor, value)}</strong>
              </label>
              <button
                className="text-button"
                disabled={busy}
                onClick={() => {
                  setValue(f?.nominal ?? 0);
                  key.current = actionKey("incident");
                }}
              >
                <RotateCcw size={12} />
                Use nominal
              </button>
            </div>
            <input
              id="fork-value"
              aria-label={`Intervention ${human(factor)}`}
              type="range"
              min={f?.min}
              max={f?.max}
              step={factor === "friction" ? 0.01 : f?.step}
              value={value}
              disabled={busy}
              onChange={(e) => {
                setValue(Number(e.target.value));
                key.current = actionKey("incident");
              }}
            />
            <div className="fork-range">
              <span>{valueText(factor, f?.min)}</span>
              <span>{valueText(factor, f?.max)}</span>
            </div>
            <div className="fork-invariants">
              <span>
                <Check size={12} />
                Frozen checkpoint {shortHash(selected?.checkpoint_hash)}
              </span>
              <span>
                <Check size={12} />
                Same task & paired nuisance
              </span>
              <span>
                <Check size={12} />
                One factor changes
              </span>
            </div>
            <div className="fork-submit">
              <span>
                {value === from
                  ? "Choose a value different from the source."
                  : `${2 * (repeats + 1)} physical episodes · ${repeats} fresh pairs + 1 anchor`}
              </span>
              <button
                className="button button-primary"
                disabled={!valid || busy}
                onClick={() => void start()}
              >
                {busy ? (
                  <LoaderCircle size={15} className="spin" />
                ) : (
                  <Play size={15} />
                )}
                {pending
                  ? "Submitting…"
                  : running(job)
                    ? "Simulation running"
                    : "Run paired experiment"}
              </button>
            </div>
          </div>
          <div
            className="fork-branch-map"
            aria-label="Tested and untested interventions"
          >
            <div className="fork-node">
              <span className="mono">SOURCE INCIDENT</span>
              <strong>{human(selected?.terminal_reason)}</strong>
              <span>Recorded failure</span>
            </div>
            <div className="fork-branch-lines" aria-hidden="true" />
            <div className="fork-branch-options">
              <div
                className={`fork-node ${selectedMatchesJob && completed ? "tested" : "untested"}`}
              >
                <GitBranch size={15} />
                <div>
                  <strong>
                    {human(factor)} → {valueText(factor, value)}
                  </strong>
                  <span>
                    {selectedMatchesJob &&
                    completed &&
                    job.validity?.valid === true
                      ? `Measured: ${sourcePasses}/${fresh.length} → ${interventionPasses}/${fresh.length} fresh successes`
                      : selectedMatchesJob && running(job)
                        ? "This intervention is running · outcomes pending"
                        : "Selected intervention · not yet tested"}
                  </span>
                </div>
              </div>
              <div className="fork-node untested">
                <X size={14} />
                <div>
                  <strong>Other combinations</strong>
                  <span>Untested · no inferred outcome</span>
                </div>
              </div>
            </div>
          </div>
        </>
      ) : context ? (
        <p className="drawer-intro">
          This campaign has no eligible development failure. Select the recorded
          v2 campaign to open its incident tests.
        </p>
      ) : null}
      {job ? (
        <section className="fork-results">
          <div className="fork-result-heading">
            <div>
              <Eyebrow>ACTUAL SIMULATION / {job.id}</Eyebrow>
              <h2>{resultTitle}</h2>
            </div>
            <Status value={job.status} />
            {running(job) ? (
              <button
                className="button button-quiet button-small"
                disabled={pending}
                onClick={() => void cancel()}
              >
                <Square size={12} />
                Cancel run
              </button>
            ) : null}
          </div>
          <p className="fork-submitted">
            Submitted: {human(job.config.factor)}{" "}
            {valueText(str(job.config.factor), job.config.from_value)} →{" "}
            {valueText(str(job.config.factor), job.config.value)} ·{" "}
            {num(job.config.nuisance_repeats)} fresh paired draws + anchor
          </p>
          <p className="fork-source-binding mono">
            Source {str(job.config.source_episode_id)} · checkpoint{" "}
            {shortHash(str(job.config.checkpoint_hash))}
          </p>
          <p
            className="fork-progress"
            role="status"
            aria-live="polite"
            aria-atomic="true"
          >
            {interrupted ? "Partial evidence retained" : job.progress?.message}{" "}
            <span className="mono">
              {interrupted
                ? `${job.progress?.completed ?? 0} of ${job.progress?.total ?? "—"} physical episodes completed`
                : `${job.progress?.completed ?? 0} / ${job.progress?.total ?? "—"}`}
            </span>
          </p>
          {job.error ? (
            <ErrorMessage
              error={
                typeof job.error === "string"
                  ? job.error
                  : JSON.stringify(job.error)
              }
            />
          ) : null}
          {fresh.length ? (
            <div className="fork-score-row">
              <div>
                <span>Original scene</span>
                <strong>
                  {sourcePasses}
                  <small> / {fresh.length}</small>
                </strong>
                <span>fresh successes</span>
              </div>
              <ArrowRight size={22} />
              <div>
                <span>Intervened scene</span>
                <strong>
                  {interventionPasses}
                  <small> / {fresh.length}</small>
                </strong>
                <span>fresh successes</span>
              </div>
              <p>
                <strong className="fork-paired-effects">
                  {rescues} failure → success
                  <br />
                  {regressions} success → failure
                </strong>
                Descriptive paired diagnostic. Small samples do not establish a
                robust operating envelope or a policy improvement.
              </p>
            </div>
          ) : null}
          {fresh.length && pairedEffect.delta_interval ? (
            <div className="fork-uncertainty">
              <strong>
                Fresh paired success difference:{" "}
                {(num(pairedEffect.delta) * 100).toFixed(1)} percentage points
              </strong>
              <span>
                95% paired interval{" "}
                {differenceIntervalText(pairedEffect.delta_interval)}
                {assessment === "inconclusive"
                  ? " · Includes zero; direction remains unresolved."
                  : " · Conditional on the tested scene and nuisance distribution."}
              </span>
              <details>
                <summary>Interval method & scope</summary>
                <p>
                  {str(
                    pairedEffect.interval_method,
                    "Conservative paired 95% difference interval.",
                  )}{" "}
                  Source-seed anchor excluded. This diagnostic does not alter
                  the frozen release decision.
                </p>
              </details>
            </div>
          ) : null}
          {typeof job.config.planner_receipt_sha === "string" ? (
            <IncidentPlannerEvidence
              receiptSha={job.config.planner_receipt_sha}
              outcome={resultTitle}
            />
          ) : null}
          {replayPair ? (
            <>
              <div className="fork-anchor-label">
                <span className="mono">
                  {replayPair.trial_index === 0
                    ? "SOURCE-SEED ANCHOR"
                    : `FRESH PAIRED DRAW ${replayPair.trial_index}`}
                </span>
                <span>
                  Original:{" "}
                  {replayPair.original.success
                    ? "success"
                    : human(replayPair.original.terminal_reason)}{" "}
                  → Intervention:{" "}
                  {replayPair.intervention.success
                    ? "success"
                    : human(replayPair.intervention.terminal_reason)}
                </span>
              </div>
              <ReplayPair
                key={`${job.id}-${replayPair.trial_index}`}
                campaign={campaign}
                camera={camera}
                onCamera={onCamera}
                leftUrl={replayPair.original.episode_url}
                rightUrl={replayPair.intervention.episode_url}
                leftLabel={
                  replayPair.trial_index === 0
                    ? "Original scene · anchor"
                    : "Original scene · fresh draw"
                }
                rightLabel="One-factor intervention"
                compact
              />
            </>
          ) : null}
          {pairs.length ? (
            <div className="table-scroll fork-pair-table">
              <table>
                <caption>
                  Measured paired outcomes — anchor excluded from fresh counts
                </caption>
                <thead>
                  <tr>
                    <th>Draw</th>
                    <th>Original</th>
                    <th>Intervention</th>
                    <th>Pair validity</th>
                  </tr>
                </thead>
                <tbody>
                  {pairs.map((pair) => (
                    <tr key={pair.trial_index}>
                      <td className="mono">
                        <button
                          className="fork-replay-draw"
                          aria-pressed={
                            replayPair?.trial_index === pair.trial_index
                          }
                          onClick={() => setReplayTrial(pair.trial_index)}
                        >
                          {pair.trial_index === 0
                            ? "Replay anchor"
                            : `Replay fresh ${pair.trial_index}`}
                        </button>
                        <small>seed {pair.seed}</small>
                      </td>
                      <td
                        className={
                          pair.original.success ? "pass-text" : "fail-text"
                        }
                      >
                        {pair.original.success
                          ? "Success"
                          : human(pair.original.terminal_reason)}
                      </td>
                      <td
                        className={
                          pair.intervention.success ? "pass-text" : "fail-text"
                        }
                      >
                        {pair.intervention.success
                          ? "Success"
                          : human(pair.intervention.terminal_reason)}
                      </td>
                      <td>
                        {pair.validity?.valid === true
                          ? "Verified"
                          : pair.validity?.valid === false
                            ? "Failed checks"
                            : "Pending checks"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {completed ? <IncidentExport key={job.id} id={job.id} /> : null}
          <JsonDetails
            value={job}
            label="Inspect run provenance, pairing and artifact hashes"
          />
        </section>
      ) : null}
      {history.length ? (
        <section className="fork-history">
          <Eyebrow>RETAINED DIAGNOSTIC RUNS</Eyebrow>
          {history.map((item) => (
            <button
              key={item.id}
              disabled={busy || !context}
              onClick={() => void inspect(item.id)}
            >
              <span>
                <strong>
                  {human(item.config.factor)} →{" "}
                  {valueText(str(item.config.factor), item.config.value)}
                </strong>
                <small className="mono">{item.id}</small>
              </span>
              <Status value={item.id === job?.id ? job.status : item.status} />
              <ArrowRight size={14} />
            </button>
          ))}
        </section>
      ) : null}
    </Drawer>
  );
}
