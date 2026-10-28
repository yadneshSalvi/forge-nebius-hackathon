import { useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  ChevronRight,
  LoaderCircle,
  Pause,
  Play,
  Plus,
  Square,
} from "lucide-react";
import { actionKey, mutateCampaign } from "./api";
import {
  activeStatus,
  episodeVerdict,
  human,
  isSuccess,
  num,
  paramsOf,
  record,
  str,
  textOf,
} from "./data";
import { CampaignStages, parameterValue } from "./Workcell";
import {
  DataDetails,
  Drawer,
  Empty,
  ErrorMessage,
  Eyebrow,
  JsonDetails,
  PageHeading,
  Panel,
  SectionTitle,
  Status,
} from "./ui";
import type { Campaign, CampaignSummary, EpisodeSummary } from "./types";

export function Campaigns({
  campaign,
  campaigns,
  onSelect,
  onLaunch,
  onEpisode,
  onRefresh,
  onInspect,
}: {
  campaign: Campaign | null;
  campaigns: CampaignSummary[];
  onSelect: (id: string) => void;
  onLaunch: () => void;
  onEpisode: (id: string) => void;
  onRefresh: () => void;
  onInspect: () => void;
}) {
  const [filter, setFilter] = useState("all");
  const [action, setAction] = useState("");
  const [pending, setPending] = useState("");
  const [error, setError] = useState("");
  const mutationKey = useRef("");
  const episodes = campaign?.episodes || [];
  const outcomes = useMemo(
    () =>
      episodes.reduce(
        (acc, e) => {
          const s = episodeVerdict(e);
          if (isSuccess(s)) acc.success++;
          else if (["failure", "failed"].includes(s)) acc.failure++;
          else if (s.includes("invalid")) acc.invalid++;
          else if (s.includes("interrupt") || s.includes("cancel"))
            acc.interrupted++;
          else acc.other++;
          return acc;
        },
        { success: 0, failure: 0, invalid: 0, interrupted: 0, other: 0 },
      ),
    [episodes],
  );
  const filtered =
    filter === "all"
      ? episodes
      : episodes.filter((e) =>
          filter === "success"
            ? isSuccess(episodeVerdict(e))
            : episodeVerdict(e).includes(filter),
        );
  async function perform(nextAction: string) {
    if (!campaign) return;
    setPending(nextAction);
    setError("");
    if (action !== nextAction || !mutationKey.current)
      mutationKey.current = actionKey(nextAction);
    try {
      await mutateCampaign(
        campaign.id,
        nextAction,
        campaign.generation,
        mutationKey.current,
      );
      setAction("");
      mutationKey.current = "";
      onRefresh();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "The action could not be confirmed.",
      );
    } finally {
      setPending("");
    }
  }
  return (
    <>
      <PageHeading
        number="02"
        label="BOUNDED EXPLORATION"
        title="Every search has an envelope."
        description="A durable campaign records its search budget, physical trials, reduction history, and immutable experiment lineage."
        actions={
          <button className="button button-primary" onClick={onLaunch}>
            <Plus size={16} />
            New campaign
          </button>
        }
      />
      <div className="campaign-layout">
        <aside className="campaign-library" aria-label="Campaign library">
          <div className="library-heading">
            <Eyebrow>CAMPAIGNS</Eyebrow>
            <span className="mono">
              {campaigns.length.toString().padStart(2, "0")}
            </span>
          </div>
          {campaigns.length ? (
            campaigns.map((c) => (
              <button
                key={c.id}
                className={`campaign-select ${campaign?.id === c.id ? "selected" : ""}`}
                onClick={() => onSelect(c.id)}
                aria-pressed={campaign?.id === c.id}
              >
                <div>
                  <span className="mono campaign-id">{c.id.slice(-10)}</span>
                  {c.recorded ? (
                    <span className="recorded-badge">RECORDED</span>
                  ) : null}
                </div>
                <strong>{c.name}</strong>
                <Status value={c.status} />
                <p>
                  {human(c.stage)}
                  <ChevronRight size={13} />
                </p>
              </button>
            ))
          ) : (
            <Empty
              title="No campaigns yet"
              action={
                <button className="text-button" onClick={onLaunch}>
                  Start a campaign
                  <ArrowRight size={14} />
                </button>
              }
            >
              Create an immutable experiment to begin.
            </Empty>
          )}
        </aside>
        <div className="campaign-detail">
          {campaign ? (
            <>
              <Panel className="campaign-status-panel">
                <div className="campaign-status-heading">
                  <div>
                    <div className="campaign-record-label">
                      <span className="mono">{campaign.id}</span>
                      <span>
                        {campaign.recorded
                          ? "Recorded evidence"
                          : "Live local worker"}
                      </span>
                    </div>
                    <h2>{campaign.name}</h2>
                  </div>
                  <Status value={campaign.status} />
                </div>
                <div className="progress-label">
                  <span>
                    {campaign.progress?.message || human(campaign.stage)}
                  </span>
                  <strong className="mono">
                    {campaign.progress?.completed ?? 0}
                    <span> / {campaign.progress?.total ?? 0}</span>
                  </strong>
                </div>
                <div
                  className="progress-track"
                  role="progressbar"
                  aria-label="Campaign stage progress"
                  aria-valuemin={0}
                  aria-valuemax={campaign.progress?.total || 1}
                  aria-valuenow={Math.min(
                    campaign.progress?.completed || 0,
                    campaign.progress?.total || 1,
                  )}
                >
                  <span
                    style={{
                      width: `${Math.min(100, ((campaign.progress?.completed || 0) / (campaign.progress?.total || 1)) * 100)}%`,
                    }}
                  />
                </div>
                <CampaignStages campaign={campaign} />
                <div className="campaign-actions">
                  <span className="mono">
                    GEN {campaign.generation} · SEED{" "}
                    {str(campaign.config?.seed)}
                  </span>
                  {["paused", "interrupted"].includes(campaign.status) ? (
                    <button
                      className="button button-small button-quiet"
                      disabled={!!pending}
                      onClick={() => void perform("resume")}
                    >
                      {pending === "resume" ? (
                        <LoaderCircle className="spin" size={13} />
                      ) : (
                        <Play size={13} />
                      )}
                      Resume
                    </button>
                  ) : activeStatus(campaign.status) ? (
                    <button
                      className="button button-small button-quiet"
                      disabled={
                        !!pending ||
                        campaign.status === "pause_requested" ||
                        campaign.status === "cancel_requested"
                      }
                      onClick={() => void perform("pause")}
                    >
                      {pending === "pause" ? (
                        <LoaderCircle className="spin" size={13} />
                      ) : (
                        <Pause size={13} />
                      )}
                      Pause at boundary
                    </button>
                  ) : null}
                  {activeStatus(campaign.status) ||
                  campaign.status === "paused" ? (
                    <button
                      className="button button-small button-danger"
                      disabled={!!pending}
                      onClick={() => {
                        setAction("cancel");
                        mutationKey.current = actionKey("cancel");
                      }}
                    >
                      <Square size={12} />
                      Cancel campaign
                    </button>
                  ) : null}
                  {campaign.counterexample ? (
                    <button className="text-button" onClick={onInspect}>
                      Inspect failure
                      <ArrowUpRight size={14} />
                    </button>
                  ) : null}
                </div>
                {campaign.status === "pause_requested" ? (
                  <p className="state-explanation">
                    Pause requested. The worker is completing a safe boundary;
                    compute is not yet confirmed stopped.
                  </p>
                ) : campaign.status === "cancel_requested" ? (
                  <p className="state-explanation">
                    Cancellation requested. Waiting for worker termination to be
                    confirmed.
                  </p>
                ) : campaign.status === "interrupted" ? (
                  <p className="state-explanation">
                    The previous worker attempt was interrupted. Its incomplete
                    evidence is retained; resume creates a new fenced
                    generation.
                  </p>
                ) : null}
                {error ? (
                  <ErrorMessage error={error} retry={onRefresh} />
                ) : null}
                {campaign.error ? (
                  <JsonDetails
                    value={campaign.error}
                    label="Worker error details"
                  />
                ) : null}
              </Panel>
              <div className="episode-totals">
                <div>
                  <span className="mono">{episodes.length}</span>
                  <span>Recorded trials</span>
                </div>
                <div>
                  <span className="mono pass-text">{outcomes.success}</span>
                  <span>Successes</span>
                </div>
                <div>
                  <span className="mono fail-text">{outcomes.failure}</span>
                  <span>Task failures</span>
                </div>
                <div>
                  <span className="mono warn-text">{outcomes.invalid}</span>
                  <span>Invalid scenes</span>
                </div>
                <div>
                  <span className="mono muted">
                    {outcomes.interrupted + outcomes.other}
                  </span>
                  <span>Other / interrupted</span>
                </div>
              </div>
              <Panel className="matrix-panel">
                <SectionTitle
                  eyebrow="ACTUAL TRIALS / NO INFERRED SURFACE"
                  title="The measured failure landscape"
                  detail="Select a point to inspect its scene, oracle verdict, and sampled trajectory."
                />
                <CampaignMatrix episodes={episodes} onEpisode={onEpisode} />
              </Panel>
              <Panel className="episode-table-panel">
                <SectionTitle title="Episode ledger">
                  <label className="select-label">
                    <span className="sr-only">Filter episodes by outcome</span>
                    <select
                      value={filter}
                      onChange={(e) => setFilter(e.target.value)}
                    >
                      <option value="all">All outcomes</option>
                      <option value="success">Successes</option>
                      <option value="failure">Task failures</option>
                      <option value="invalid">Invalid scenes</option>
                      <option value="interrupted">Interrupted</option>
                    </select>
                  </label>
                </SectionTitle>
                <EpisodeTable episodes={filtered} onEpisode={onEpisode} />
              </Panel>
              <Panel className="event-log">
                <SectionTitle
                  eyebrow="DURABLE HISTORY"
                  title="Worker event trail"
                />
                {campaign.events?.length ? (
                  <ol>
                    {campaign.events
                      .slice(-7)
                      .reverse()
                      .map((event, i) => (
                        <li key={str(event.id, i.toString())}>
                          <span className="event-node" />
                          <span className="mono event-time">
                            {formatTimestamp(
                              event.at ?? event.created_at ?? event.timestamp,
                            )}
                          </span>
                          <div>
                            <strong>
                              {human(event.type ?? event.kind ?? event.event)}
                            </strong>
                            <p>
                              {str(
                                event.message ??
                                  record(event.payload).message ??
                                  record(event.data).message,
                                textOf(event.payload ?? event.data, ""),
                              )}
                            </p>
                          </div>
                        </li>
                      ))}
                  </ol>
                ) : (
                  <p className="muted">
                    The worker has not published events yet.
                  </p>
                )}
              </Panel>
            </>
          ) : (
            <Empty title="Select an experiment">
              The recorded campaign is available without starting compute.
            </Empty>
          )}
        </div>
      </div>
      {action === "cancel" && campaign ? (
        <Drawer
          title="Cancel this campaign?"
          eyebrow="STOP LOCAL EXECUTION"
          onClose={() => setAction("")}
          footer={
            <>
              <button
                className="button button-quiet"
                onClick={() => setAction("")}
              >
                Keep running
              </button>
              <button
                className="button button-danger"
                disabled={!!pending}
                onClick={() => void perform("cancel")}
              >
                {pending ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Square size={14} />
                )}
                Confirm cancellation
              </button>
            </>
          }
        >
          <p className="drawer-intro">
            The worker will stop scheduling and terminate this local attempt.
            Completed artifacts remain available. Incomplete trajectories are
            retained as interrupted attempts.
          </p>
          <DataDetails
            value={{
              campaign: campaign.name,
              id: campaign.id,
              generation: campaign.generation,
              stage: campaign.stage,
            }}
          />
          {error ? <ErrorMessage error={error} /> : null}
        </Drawer>
      ) : null}
    </>
  );
}
function formatTimestamp(value: unknown) {
  const s = str(value, "");
  if (!s) return "—";
  const date = new Date(s);
  return Number.isNaN(date.getTime())
    ? s
    : date.toLocaleTimeString([], {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
}
export function EpisodeTable({
  episodes,
  onEpisode,
}: {
  episodes: EpisodeSummary[];
  onEpisode: (id: string) => void;
}) {
  const [limit, setLimit] = useState(20);
  return episodes.length ? (
    <>
      <div
        className="table-scroll"
        tabIndex={0}
        aria-label="Episode ledger, scrollable"
      >
        <table>
          <caption className="sr-only">
            Recorded physical episodes and their actual outcomes
          </caption>
          <thead>
            <tr>
              <th>Episode</th>
              <th>Family</th>
              <th>Policy</th>
              <th>Outcome</th>
              <th>
                <span className="sr-only">Inspect</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {episodes.slice(0, limit).map((e) => (
              <tr key={e.id}>
                <td className="mono">
                  <button
                    className="table-link"
                    onClick={() => onEpisode(e.id)}
                  >
                    {e.id.slice(-16)}
                  </button>
                </td>
                <td>{human(e.family ?? e.scenario?.family ?? e.stage)}</td>
                <td className="mono table-policy">
                  {str(e.policy_id ?? record(e.policy).policy_id)}
                </td>
                <td>
                  <Status value={episodeVerdict(e)} />
                </td>
                <td>
                  <button
                    className="icon-button"
                    aria-label={`Inspect episode ${e.id}`}
                    onClick={() => onEpisode(e.id)}
                  >
                    <ArrowUpRight size={15} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {episodes.length > limit ? (
        <button
          className="text-button table-more"
          onClick={() => setLimit((v) => v + 30)}
        >
          Show 30 more episodes
          <ArrowRight size={14} />
        </button>
      ) : null}
      <div className="table-caption mono">
        Showing {Math.min(limit, episodes.length)} / {episodes.length} recorded
        episodes
      </div>
    </>
  ) : (
    <Empty title="No matching episodes">
      Trials appear here as the worker publishes verified artifacts.
    </Empty>
  );
}
function CampaignMatrix({
  episodes,
  onEpisode,
}: {
  episodes: EpisodeSummary[];
  onEpisode: (id: string) => void;
}) {
  const [xKey, setXKey] = useState("obstacle_height");
  const [yKey, setYKey] = useState("friction");
  const keys = useMemo(
    () => [
      ...new Set(
        episodes.flatMap((e) =>
          Object.entries(paramsOf(e))
            .filter(([, v]) => typeof v === "number")
            .map(([k]) => k),
        ),
      ),
    ],
    [episodes],
  );
  const x = keys.includes(xKey) ? xKey : keys[0];
  const y = keys.includes(yKey) ? yKey : keys[1];
  const points = episodes
    .map((e) => ({ e, p: paramsOf(e) }))
    .filter(({ p }) => typeof p[x] === "number" && typeof p[y] === "number");
  const xs = points.map(({ p }) => num(p[x]));
  const ys = points.map(({ p }) => num(p[y]));
  const minX = Math.min(...xs),
    maxX = Math.max(...xs),
    minY = Math.min(...ys),
    maxY = Math.max(...ys);
  const px = (v: number) => 70 + ((v - minX) / (maxX - minX || 1)) * 620;
  const py = (v: number) => 260 - ((v - minY) / (maxY - minY || 1)) * 220;
  return (
    <>
      <div className="matrix-control-row">
        <div className="chart-legend">
          <span>
            <i className="pass-dot" />
            Success
          </span>
          <span>
            <i className="fail-dot" />
            Task failure
          </span>
          <span>
            <i className="warn-dot" />
            Invalid / interrupted
          </span>
          <span>
            <i className="untested-swatch" />
            Untested space
          </span>
        </div>
        <div className="axis-selects">
          <label>
            X{" "}
            <select
              value={x || ""}
              onChange={(e) => setXKey(e.target.value)}
              aria-label="Matrix horizontal parameter"
            >
              {keys.map((k) => (
                <option key={k} value={k}>
                  {human(k)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Y{" "}
            <select
              value={y || ""}
              onChange={(e) => setYKey(e.target.value)}
              aria-label="Matrix vertical parameter"
            >
              {keys.map((k) => (
                <option key={k} value={k}>
                  {human(k)}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      {points.length ? (
        <div className="matrix-chart">
          <svg
            viewBox="0 0 750 320"
            role="group"
            aria-label={`${human(y)} by ${human(x)}. ${points.length} measured episodes. Episode ledger provides equivalent accessible outcomes.`}
          >
            <defs>
              <pattern
                id="untested-hatch"
                width="7"
                height="7"
                patternUnits="userSpaceOnUse"
              >
                <path
                  d="M-1 1 1-1M0 7 7 0M6 8 8 6"
                  stroke="#2b3b47"
                  strokeWidth=".5"
                />
              </pattern>
            </defs>
            <rect
              x="70"
              y="35"
              width="620"
              height="225"
              fill="url(#untested-hatch)"
            />
            {[0, 0.25, 0.5, 0.75, 1].map((v) => (
              <g key={v}>
                <line
                  x1="70"
                  y1={260 - v * 220}
                  x2="690"
                  y2={260 - v * 220}
                  stroke="#344454"
                  strokeWidth=".6"
                />
                <line
                  x1={70 + v * 620}
                  y1="35"
                  x2={70 + v * 620}
                  y2="260"
                  stroke="#344454"
                  strokeWidth=".6"
                />
                <text x="56" y={264 - v * 220} textAnchor="end">
                  {parameterValue(y, minY + v * (maxY - minY))}
                </text>
                <text x={70 + v * 620} y="282" textAnchor="middle">
                  {parameterValue(x, minX + v * (maxX - minX))}
                </text>
              </g>
            ))}
            {points.map(({ e, p }, i) => {
              const verdict = episodeVerdict(e);
              const success = isSuccess(verdict);
              return (
                <circle
                  key={`${e.id}-${i}`}
                  cx={px(num(p[x]))}
                  cy={py(num(p[y]))}
                  r="4.3"
                  fill={
                    success
                      ? "#6ee7b7"
                      : ["failure", "failed"].includes(verdict)
                        ? "#f4a0ac"
                        : "#fcd34d"
                  }
                  stroke="#15202b"
                  strokeWidth="1.5"
                  opacity=".9"
                  role="button"
                  tabIndex={0}
                  aria-label={`${e.id}: ${human(verdict)}; ${human(x)} ${parameterValue(x, p[x])}; ${human(y)} ${parameterValue(y, p[y])}`}
                  onClick={() => onEpisode(e.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onEpisode(e.id);
                    }
                  }}
                >
                  <title>
                    {e.id} · {human(verdict)}
                  </title>
                </circle>
              );
            })}
            <text x="380" y="312" textAnchor="middle">
              {human(x).toUpperCase()}
            </text>
          </svg>
        </div>
      ) : (
        <Empty title="The landscape is still untested">
          Actual parameterized episodes will populate this plot. Empty space
          carries no predicted outcome.
        </Empty>
      )}
      <p className="chart-footnote">
        All available parameterized episodes shown; repeated coordinates
        overlap. The ledger retains every trial and its unique seed.
      </p>
    </>
  );
}
