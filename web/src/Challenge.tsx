import { useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  FlaskConical,
  LoaderCircle,
  Play,
  SlidersHorizontal,
} from "lucide-react";
import { actionKey, request } from "./api";
import { human, num, record, str } from "./data";
import { parameterValue } from "./Workcell";
import { ReplayPair } from "./Replay";
import {
  ErrorMessage,
  Eyebrow,
  JsonDetails,
  Panel,
  SectionTitle,
  Status,
} from "./ui";
import type { Bootstrap, Campaign } from "./types";

const parameterKeys = [
  "obstacle_height",
  "friction",
  "payload_yaw",
  "tray_offset_y",
];
export function ChallengeForm({
  campaign,
  bootstrap,
  onCreated,
}: {
  campaign: Campaign;
  bootstrap: Bootstrap | null;
  onCreated: (c: Campaign) => void;
}) {
  const factors = record(bootstrap?.task.factors);
  const [values, setValues] = useState<Record<string, number>>(() =>
    Object.fromEntries(
      parameterKeys.map((k) => [k, num(record(factors[k]).nominal)]),
    ),
  );
  const [seed, setSeed] = useState("2027");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const key = useRef(actionKey("challenge"));
  const validSeed =
    /^\d+$/.test(seed) &&
    Number.isSafeInteger(Number(seed)) &&
    Number(seed) <= 1000000000;
  async function run() {
    setPending(true);
    setError("");
    try {
      const result = await request<Campaign>("/challenges", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": key.current,
        },
        body: JSON.stringify({
          campaign_id: campaign.id,
          seed: Number(seed),
          parameters: values,
        }),
      });
      onCreated(result);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "The paired challenge did not start.",
      );
    } finally {
      setPending(false);
    }
  }
  return (
    <Panel className="challenge-panel">
      <SectionTitle
        eyebrow="FROZEN WEIGHTS / A NEW CONDITION"
        title="Put the policy to the test."
        detail="Choose a physical condition. Run the frozen base and nominated revision under the same scene and nuisance seed."
      >
        <SlidersHorizontal size={20} />
      </SectionTitle>
      <div className="challenge-parameters">
        {parameterKeys.map((k) => {
          const f = record(factors[k]);
          return (
            <div className="challenge-parameter" key={k}>
              <label htmlFor={`challenge-${k}`}>
                {human(k)}
                <strong className="mono">{parameterValue(k, values[k])}</strong>
              </label>
              <input
                id={`challenge-${k}`}
                type="range"
                min={num(f.min)}
                max={num(f.max, 1)}
                step={k === "friction" ? 0.01 : num(f.step, 0.01)}
                value={values[k]}
                onChange={(e) => {
                  setValues((v) => ({ ...v, [k]: Number(e.target.value) }));
                  key.current = actionKey("challenge");
                }}
              />
              <div>
                <span>{parameterValue(k, f.min)}</span>
                <span>{parameterValue(k, f.max)}</span>
              </div>
            </div>
          );
        })}
      </div>
      <div className="challenge-run-row">
        <label>
          NUISANCE SEED
          <input
            value={seed}
            inputMode="numeric"
            aria-invalid={!validSeed}
            onChange={(e) => {
              setSeed(e.target.value);
              key.current = actionKey("challenge");
            }}
          />
        </label>
        <div>
          <span>
            <Check size={12} />2 physical episodes · no retraining
          </span>
          <small>
            Live simulation challenge; separate from sealed evaluation.
          </small>
        </div>
        <button
          className="button button-primary"
          onClick={() => void run()}
          disabled={pending || !validSeed || !Object.keys(factors).length}
        >
          {pending ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <Play size={14} />
          )}{" "}
          {pending ? "Starting challenge…" : "Run paired challenge"}
          <ArrowRight size={14} />
        </button>
      </div>
      {error ? <ErrorMessage error={error} /> : null}
    </Panel>
  );
}
export function ChallengeOutcome({
  campaign,
  camera,
  onCamera,
  onParent,
}: {
  campaign: Campaign;
  camera: string;
  onCamera: (s: string) => void;
  onParent: (id: string) => void;
}) {
  const challenge = record(campaign.challenge);
  const parentId = str(
    challenge.source_campaign_id ??
      challenge.campaign_id ??
      campaign.config.source_campaign_id ??
      campaign.config.parent_campaign_id ??
      campaign.config.campaign_id,
    "",
  );
  const hasVerdicts =
    typeof challenge.base_success === "boolean" &&
    typeof challenge.revised_success === "boolean";
  return (
    <>
      <div className="challenge-outcome-header">
        <div>
          <Eyebrow>LIVE SIMULATION CHALLENGE</Eyebrow>
          <h2>One condition. Two frozen policies.</h2>
          <p>
            {str(
              challenge.label,
              "The local worker is executing a paired challenge. This is not sealed evaluation.",
            )}
          </p>
        </div>
        <Status value={campaign.status} />
      </div>
      <Panel className="challenge-condition">
        <div>
          <Eyebrow>IMMUTABLE PHYSICAL CONDITION</Eyebrow>
          <div className="challenge-condition-values">
            {Object.entries(
              record(challenge.parameters ?? campaign.config.parameters),
            ).map(([k, v]) => (
              <div key={k}>
                <span>{human(k)}</span>
                <strong className="mono">{parameterValue(k, v)}</strong>
              </div>
            ))}
            <div>
              <span>Nuisance seed</span>
              <strong className="mono">
                {str(challenge.seed ?? campaign.config.seed)}
              </strong>
            </div>
          </div>
        </div>
        <div className="challenge-verdicts">
          <div>
            <span>Frozen base</span>
            <Status
              value={
                hasVerdicts
                  ? challenge.base_success
                    ? "success"
                    : "failure"
                  : "pending"
              }
            />
          </div>
          <ArrowRight size={17} />
          <div>
            <span>Nominated revision</span>
            <Status
              value={
                hasVerdicts
                  ? challenge.revised_success
                    ? "success"
                    : "failure"
                  : "pending"
              }
            />
          </div>
        </div>
      </Panel>
      <ReplayPair
        campaign={campaign}
        camera={camera}
        onCamera={onCamera}
        leftId={str(challenge.base_episode_id, "")}
        rightId={str(challenge.revised_episode_id, "")}
        leftLabel="Frozen base policy"
        rightLabel="Nominated revision"
      />
      <div className="challenge-caption">
        <FlaskConical size={17} />
        <p>
          The measured task oracle decides each verdict. This condition does not
          update weights or change the registered release decision.
        </p>
        {parentId ? (
          <button className="text-button" onClick={() => onParent(parentId)}>
            <ArrowLeft size={13} />
            Return to policy experiment
          </button>
        ) : null}
      </div>
      <JsonDetails value={challenge} label="Paired challenge manifest" />
    </>
  );
}
