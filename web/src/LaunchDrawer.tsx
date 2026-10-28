import { useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  FlaskConical,
  LoaderCircle,
  Play,
} from "lucide-react";
import { actionKey, mutateCampaign, request } from "./api";
import { array, human, record, shortHash, str } from "./data";
import {
  DataDetails,
  DefinitionList,
  Drawer,
  ErrorMessage,
  Eyebrow,
  JsonDetails,
} from "./ui";
import type { Bootstrap, Campaign } from "./types";

export function LaunchDrawer({
  bootstrap,
  onClose,
  onCreated,
}: {
  bootstrap: Bootstrap | null;
  onClose: () => void;
  onCreated: (campaign: Campaign) => void;
}) {
  const [step, setStep] = useState(0);
  const [name, setName] = useState("");
  const [seed, setSeed] = useState("47");
  const [budget, setBudget] = useState<12 | 24 | 36>(24);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const key = useRef(actionKey("create"));
  const validSeed =
    /^\d+$/.test(seed) &&
    Number.isSafeInteger(Number(seed)) &&
    Number(seed) <= 1000000000;
  const task = bootstrap?.task || {};
  async function launch() {
    setPending(true);
    setError("");
    try {
      const campaign = await request<Campaign>("/campaigns", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": key.current,
        },
        body: JSON.stringify({
          ...(name.trim() ? { name: name.trim() } : {}),
          seed: Number(seed),
          search_budget: budget,
        }),
      });
      onCreated(campaign);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Could not create campaign.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <Drawer
      title={
        step === 0
          ? "A new search. A frozen experiment."
          : "Review the execution envelope."
      }
      eyebrow="NEW CAMPAIGN"
      onClose={onClose}
      footer={
        <>
          <span className="drawer-step">{step + 1} / 2</span>
          {step === 1 ? (
            <button
              className="button button-quiet"
              onClick={() => setStep(0)}
              disabled={pending}
            >
              <ArrowLeft size={16} />
              Back
            </button>
          ) : null}
          <button
            className="button button-primary"
            disabled={pending || !bootstrap?.base_ready || !validSeed}
            onClick={() => (step === 0 ? setStep(1) : void launch())}
          >
            {pending ? (
              <LoaderCircle size={16} className="spin" />
            ) : step === 0 ? null : (
              <Play size={15} />
            )}{" "}
            {pending
              ? "Starting campaign…"
              : step === 0
                ? "Review campaign"
                : "Start campaign"}
            {step === 0 ? <ArrowRight size={16} /> : null}
          </button>
        </>
      }
    >
      <div className="drawer-notice">
        <FlaskConical size={19} />
        <div>
          <strong>Local simulation</strong>
          <p>
            Run a bounded search against the registered task. The measured
            physics verdict determines every outcome.
          </p>
        </div>
      </div>
      {step === 0 ? (
        <>
          <label className="field">
            Campaign name <span className="optional">Optional</span>
            <input
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                key.current = actionKey("create");
              }}
              maxLength={80}
              placeholder="e.g. Clearance boundary investigation"
            />
          </label>
          <div className="frozen-task">
            <Eyebrow>REGISTERED TASK</Eyebrow>
            <h3>
              {str(task.name ?? task.title, "Cartesian kitting workcell")}
            </h3>
            <p>
              {str(
                task.description,
                "Move the payload into the target bay while preserving the neighboring object.",
              )}
            </p>
            <div className="frozen-label">
              <Check size={13} />
              Task and policy revisions are frozen at creation
            </div>
          </div>
          <fieldset className="budget-fieldset">
            <legend>Discovery budget</legend>
            <p>
              Finite candidate ceiling; replay confirmation and later stages
              follow the registered protocol.
            </p>
            <div className="budget-options">
              {([12, 24, 36] as const).map((value) => (
                <label
                  className={
                    budget === value
                      ? "budget-option selected"
                      : "budget-option"
                  }
                  key={value}
                >
                  <input
                    type="radio"
                    name="budget"
                    value={value}
                    checked={budget === value}
                    onChange={() => {
                      setBudget(value);
                      key.current = actionKey("create");
                    }}
                  />
                  <strong>{value}</strong>
                  <span>candidates</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="field">
            Scenario seed
            <input
              value={seed}
              inputMode="numeric"
              onChange={(e) => {
                setSeed(e.target.value);
                key.current = actionKey("create");
              }}
              aria-invalid={!validSeed}
              aria-describedby="seed-help"
            />
            <span id="seed-help" className="field-help">
              An integer from 0 to 1,000,000,000. Stored in the immutable
              campaign.
            </span>
          </label>
          <details className="json-details">
            <summary>Registered task and runtime</summary>
            <DataDetails value={task} />
            <DataDetails value={bootstrap?.runtime} />
          </details>
        </>
      ) : (
        <>
          <DefinitionList
            entries={[
              ["Name", name.trim() || "Automatically assigned"],
              ["Discovery ceiling", `${budget} candidate scenes`],
              ["Scenario seed", <span className="mono">{seed}</span>],
              [
                "Runtime",
                str(
                  bootstrap?.runtime.engine ??
                    bootstrap?.runtime.name ??
                    bootstrap?.runtime.simulator,
                  "Local authoritative simulator",
                ),
              ],
              ["Task revision", str(task.revision ?? task.id)],
              ["Destination", "Local durable campaign store"],
            ]}
          />
          <div className="review-block">
            <h3>What starts now</h3>
            <ol className="plain-steps">
              <li>Generate a bounded NVIDIA search plan.</li>
              <li>Run physical episodes and reduce a reproducible failure.</li>
              <li>Acquire validated corrective demonstrations.</li>
            </ol>
            <p>
              Training begins after a separate review of the acquired
              curriculum. Failed and interrupted attempts remain in the evidence
              trail.
            </p>
          </div>
          <div className="review-block">
            <h3>Compute and stop conditions</h3>
            <p>
              The local worker enforces the frozen TaskSpec and search ceiling.
              Remote model calls use the configured providers shown below. No
              cloud GPU runtime is connected.
            </p>
            <JsonDetails
              value={
                task.budgets ??
                task.limits ??
                task.training ??
                task.protocol ??
                task
              }
              label="Inspect registered budgets and protocol"
            />
          </div>
          <ProviderList providers={bootstrap?.providers} />
        </>
      )}
      {!bootstrap?.base_ready ? (
        <div className="state-explanation">
          The local base checkpoint is being prepared. Launch becomes available
          when its validated artifact is ready.
        </div>
      ) : null}
      {error ? <ErrorMessage error={error} /> : null}
    </Drawer>
  );
}
export function TrainingDrawer({
  campaign,
  onClose,
  onStarted,
}: {
  campaign: Campaign;
  onClose: () => void;
  onStarted: () => void;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const key = useRef(actionKey("train"));
  const c = campaign.curriculum;
  const valid = !!c?.demonstrations.some((d) => d.success);
  async function train() {
    setPending(true);
    setError("");
    try {
      await mutateCampaign(
        campaign.id,
        "train",
        campaign.generation,
        key.current,
      );
      onStarted();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Training did not start.");
    } finally {
      setPending(false);
    }
  }
  return (
    <Drawer
      title="Review the training experiment."
      eyebrow="CURRICULUM → POLICY"
      onClose={onClose}
      footer={
        <>
          <span className="muted">Generation {campaign.generation}</span>
          <button
            className="button button-primary"
            disabled={pending || !valid}
            onClick={() => void train()}
          >
            {pending ? (
              <LoaderCircle className="spin" size={15} />
            ) : (
              <Play size={15} />
            )}{" "}
            {pending ? "Launching training…" : "Train all registered arms"}
          </button>
        </>
      }
    >
      <p className="drawer-intro">
        Compare the targeted curriculum with its registered controls. Every arm
        starts from the same base checkpoint and uses the frozen training
        budget.
      </p>
      <DefinitionList
        entries={[
          [
            "Base checkpoint",
            <span className="mono">{shortHash(c?.base_checkpoint_sha)}</span>,
          ],
          ["Curriculum", <span className="mono">{c?.id || "Pending"}</span>],
          [
            "Validated demonstrations",
            c?.demonstrations.filter((d) => d.success).length ?? 0,
          ],
          [
            "Excluded splits",
            c?.excluded_splits.map(human).join(", ") || "Awaiting manifest",
          ],
        ]}
      />
      <h3 className="spaced-heading">Registered adaptation arms</h3>
      <div className="review-arms">
        {c?.arms.map((arm) => (
          <div key={arm.name}>
            <span className="arm-swatch" />
            <div>
              <strong>{arm.label}</strong>
              <p>
                {arm.corrective} corrective · {arm.retained_nominal} retained
                nominal · {arm.acquisition_episodes} acquisition episodes
              </p>
            </div>
          </div>
        ))}
      </div>
      <div className="review-block">
        <h3>Fixed training budget</h3>
        <DataDetails value={c?.training_budget} />
      </div>
      <div className="drawer-notice">
        <Check size={19} />
        <div>
          <strong>Measured evaluation follows training</strong>
          <p>
            The result is a development comparison under the registered public
            protocol. Sealed evaluation is controlled separately. A regression
            remains a regression.
          </p>
        </div>
      </div>
      {!valid ? (
        <ErrorMessage error="No validated successful demonstrations are available. Training is unavailable until the curriculum is complete." />
      ) : null}
      {error ? <ErrorMessage error={error} /> : null}
    </Drawer>
  );
}
export function ProviderList({ providers }: { providers: unknown }) {
  const values = Array.isArray(providers)
    ? providers
    : Object.entries(record(providers)).map(([name, p]) => ({
        name,
        ...record(p),
      }));
  return (
    <div className="provider-list">
      <Eyebrow>MODEL ROUTING</Eyebrow>
      {array(values).map((p, i) => {
        const r = record(p);
        return (
          <div key={i}>
            <span className="provider-square" />
            <div>
              <strong>
                {str(r.provider ?? r.name, "Configured provider")}
              </strong>
              <span className="mono">
                {str(
                  r.model ?? r.model_id,
                  r.status ? human(r.status) : "Awaiting route metadata",
                )}
              </span>
              {r.status ? <small>{human(r.status)}</small> : null}
            </div>
          </div>
        );
      })}
      {!values.length ? (
        <p className="muted">Provider metadata is loading.</p>
      ) : null}
      <p className="field-help">
        Receipts retain the provider and model used for each actual request.
      </p>
    </div>
  );
}
