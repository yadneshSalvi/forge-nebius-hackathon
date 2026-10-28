import {
  Component,
  lazy,
  Suspense,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ErrorInfo, ReactNode } from "react";
import {
  ArrowDownRight,
  Box,
  ChevronDown,
  Crosshair,
  Layers3,
  Maximize2,
  Pause,
  Play,
  RotateCcw,
  SkipBack,
  SkipForward,
  View,
} from "lucide-react";
import { useEpisode } from "./api";
import {
  episodeVerdict,
  fixed,
  geometryOf,
  human,
  num,
  record,
  sampleAt,
  samplesOf,
  shortHash,
  str,
} from "./data";
import {
  DataDetails,
  Drawer,
  Empty,
  ErrorMessage,
  JsonDetails,
  Loading,
  Status,
} from "./ui";
import type { Campaign, Episode, Geometry, Sample } from "./types";

const Scene3D = lazy(() => import("./Scene3D"));
class SceneBoundary extends Component<
  { children: ReactNode; fallback: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(_error: Error, _info: ErrorInfo) {
    /* The same sampled data remains available in the top view. */
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}
function TopView({
  geometries,
  sample,
  selected,
  onSelect,
}: {
  geometries: Geometry[];
  sample?: Sample;
  selected: string;
  onSelect: (body: string) => void;
}) {
  const sx = (x: number) => 250 + x * 430;
  const sy = (y: number) => 194 - y * 430;
  return (
    <svg
      className="top-view"
      viewBox="0 0 500 370"
      role="img"
      aria-label="Top view of measured geometry in the XY world plane"
    >
      <defs>
        <pattern
          id="floor-grid"
          width="43"
          height="43"
          patternUnits="userSpaceOnUse"
        >
          <path
            d="M 43 0 L 0 0 0 43"
            fill="none"
            stroke="#3a5060"
            strokeWidth=".7"
          />
        </pattern>
      </defs>
      <rect
        x="14"
        y="14"
        width="472"
        height="342"
        rx="5"
        fill="url(#floor-grid)"
      />
      <path
        d="M250 20V350M22 194H478"
        stroke="#647681"
        strokeWidth=".7"
        strokeDasharray="3 5"
      />
      {geometries
        .filter((g) => g.type !== "plane" && !/floor|ground|table/.test(g.name))
        .map((g) => {
          const body = sample?.bodies[g.body];
          const p = body?.position || [0, 0, 0];
          const q = body?.quaternion || g.quaternion;
          const yaw = Math.atan2(
            2 * (q[0] * q[3] + q[1] * q[2]),
            1 - 2 * (q[2] * q[2] + q[3] * q[3]),
          );
          const x = sx(p[0] + g.position[0]);
          const y = sy(p[1] + g.position[1]);
          const color = /protected/.test(g.name)
            ? "#d69da4"
            : /payload/.test(g.name)
              ? "#89dce5"
              : /tray|bay/.test(g.name)
                ? "#878a9e"
                : "#78909f";
          return (
            <rect
              key={g.name}
              x={x - g.size[0] * 430}
              y={y - g.size[1] * 430}
              width={Math.max(2, g.size[0] * 860)}
              height={Math.max(2, g.size[1] * 860)}
              transform={`rotate(${(-yaw * 180) / Math.PI} ${x} ${y})`}
              fill={color}
              fillOpacity={/payload|protected/.test(g.name) ? 0.86 : 0.35}
              stroke={selected === g.body ? "#c4b5fd" : color}
              strokeWidth={selected === g.body ? 2 : 1}
              onClick={() => onSelect(g.body)}
            />
          );
        })}
      <path d="M38 322h43m-43 0v-43" stroke="#b7c4d2" strokeWidth="1.5" />
      <text x="86" y="326">
        X
      </text>
      <text x="34" y="270">
        Y
      </text>
      <path d="M378 326h43m-43-4v8m43-8v8" stroke="#b7c4d2" />
      <text x="375" y="347">
        100 mm
      </text>
    </svg>
  );
}
function ScenePane({
  episode,
  loading,
  error,
  retry,
  label,
  kind,
  time,
  camera,
  trajectory,
  playing,
  selected,
  onSelect,
}: {
  episode: Episode | null;
  loading: boolean;
  error: string;
  retry: () => void;
  label: string;
  kind: string;
  time: number;
  camera: string;
  trajectory: boolean;
  playing: boolean;
  selected: string;
  onSelect: (body: string) => void;
}) {
  const samples = useMemo(() => samplesOf(episode), [episode]);
  const geoms = useMemo(() => geometryOf(episode), [episode]);
  const motionRecorded = record(episode?.trace).recorded !== false;
  const effectiveTime = motionRecorded ? time : samples.at(-1)?.t || 0;
  const { sample } = sampleAt(samples, effectiveTime);
  const fallback = (
    <TopView
      geometries={geoms}
      sample={sample}
      selected={selected}
      onSelect={onSelect}
    />
  );
  return (
    <div className={`scene-pane scene-${kind}`}>
      <div className="scene-pane-header">
        <div>
          <span className="pane-index">{kind === "source" ? "A" : "B"}</span>
          <strong>{label}</strong>
        </div>
        <span className="scene-kind">
          {motionRecorded ? "SIMULATION REPLAY" : "MEASURED FINAL STATE"}
        </span>
      </div>
      <div className="scene-canvas">
        {loading ? (
          <Loading label="Loading authoritative trace" />
        ) : error ? (
          <ErrorMessage error={error} retry={retry} />
        ) : !episode ? (
          <Empty title="Replay pending">
            The worker will publish the trace and scene geometry here.
          </Empty>
        ) : geoms.length ? (
          <SceneBoundary
            fallback={
              <>
                {fallback}
                <span className="scene-fidelity-note">
                  WebGL unavailable · sampled top view
                </span>
              </>
            }
          >
            {camera === "top" ? (
              fallback
            ) : (
              <Suspense fallback={fallback}>
                <Scene3D
                  geometries={geoms}
                  samples={samples}
                  time={effectiveTime}
                  trajectory={trajectory && motionRecorded}
                  playing={playing}
                  selected={selected}
                  onSelect={onSelect}
                />
              </Suspense>
            )}
          </SceneBoundary>
        ) : (
          <Empty title="Geometry not available">
            Use the sampled telemetry and episode evidence below.
          </Empty>
        )}
        <div className="scene-axis" aria-hidden="true">
          <svg viewBox="0 0 52 49">
            <path
              d="m23 29 20 9M23 29 7 39M23 29V6"
              stroke="#82939e"
              fill="none"
            />
            <text x="43" y="44">
              X
            </text>
            <text x="0" y="46">
              Y
            </text>
            <text x="19" y="6">
              Z
            </text>
          </svg>
        </div>
        {episode ? (
          <div className="scene-time mono">
            t {fixed(sample?.t, 2)} s
            <span>{human(sample?.raw.phase ?? "sample")}</span>
          </div>
        ) : null}
      </div>
      <div className="scene-pane-footer">
        <span className="mono">
          {episode
            ? str(episode.id ?? episode.episode_id).slice(0, 22)
            : "TRACE PENDING"}
        </span>
        {episode ? (
          <Status value={episodeVerdict(episode)} />
        ) : (
          <span className="muted">Waiting for evidence</span>
        )}
      </div>
    </div>
  );
}
export function ReplayPair({
  campaign,
  camera,
  onCamera,
  leftId,
  rightId,
  leftLabel = "Original discovery",
  rightLabel = "Reduced counterexample",
  compact = false,
}: {
  campaign: Campaign;
  camera: string;
  onCamera: (camera: string) => void;
  leftId?: string;
  rightId?: string;
  leftLabel?: string;
  rightLabel?: string;
  compact?: boolean;
}) {
  const firstFailure = campaign.episodes?.find(
    (e) => episodeVerdict(e) === "failure" || episodeVerdict(e) === "failed",
  );
  const sourceId =
    leftId ||
    campaign.counterexample?.source_episode_id ||
    firstFailure?.id ||
    campaign.episodes?.[0]?.id;
  const minimizedId = rightId || campaign.counterexample?.minimized_episode_id;
  const left = useEpisode(sourceId);
  const right = useEpisode(minimizedId);
  const leftSamples = useMemo(() => samplesOf(left.episode), [left.episode]);
  const rightSamples = useMemo(() => samplesOf(right.episode), [right.episode]);
  const leftRecorded =
    record(left.episode?.trace).recorded !== false && leftSamples.length > 2;
  const rightRecorded =
    record(right.episode?.trace).recorded !== false && rightSamples.length > 2;
  const duration = Math.max(
    leftRecorded ? leftSamples.at(-1)?.t || 0 : 0,
    rightRecorded ? rightSamples.at(-1)?.t || 0 : 0,
  );
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [keyboardHelp, setKeyboardHelp] = useState(false);
  const [shortcutsEnabled, setShortcutsEnabled] = useState(true);
  const [trajectory, setTrajectory] = useState(false);
  const [selected, setSelected] = useState("payload");
  const [objectsOpen, setObjectsOpen] = useState(false);
  const playbackRef = useRef<HTMLDivElement>(null);
  const initialized = useRef("");
  useEffect(() => {
    if (sourceId && duration && initialized.current !== sourceId) {
      initialized.current = sourceId;
      const violation = record(left.episode?.metrics?.first_violation).time;
      const initial =
        typeof violation === "number"
          ? Math.min(duration, violation + 0.08)
          : duration * 0.45;
      const reference = leftRecorded ? leftSamples : rightSamples;
      setTime(sampleAt(reference, initial).sample?.t || 0);
      setPlaying(false);
    }
  }, [
    sourceId,
    duration,
    left.episode,
    leftRecorded,
    leftSamples,
    rightSamples,
  ]);
  useEffect(() => {
    const listener = () => {
      if (document.hidden) setPlaying(false);
    };
    document.addEventListener("visibilitychange", listener);
    return () => document.removeEventListener("visibilitychange", listener);
  }, []);
  useEffect(() => {
    if (!playing || !duration) return;
    let frame = 0;
    let last = performance.now();
    let elapsed = 0;
    const tick = (now: number) => {
      const dt = Math.max(0, (now - last) / 1000);
      last = now;
      if (!document.hidden) {
        elapsed += dt;
        if (elapsed >= 1 / 30) {
          const frames = Math.floor(elapsed * 30);
          const delta = (frames / 30) * speed;
          elapsed -= frames / 30;
          setTime((t) => {
            if (t + delta >= duration) {
              setPlaying(false);
              return duration;
            }
            return t + delta;
          });
        }
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, duration, speed]);
  function step(direction: number) {
    setPlaying(false);
    const ref = leftRecorded ? leftSamples : rightRecorded ? rightSamples : [];
    const { index } = sampleAt(ref, time);
    setTime(
      ref[Math.max(0, Math.min(ref.length - 1, index + direction))]?.t || 0,
    );
  }
  function toggle() {
    if (time >= duration) setTime(0);
    setPlaying((v) => !v);
  }
  const sourceSample = sampleAt(
    leftSamples,
    leftRecorded ? time : leftSamples.at(-1)?.t || 0,
  );
  const reducedSample = sampleAt(
    rightSamples,
    rightRecorded ? time : rightSamples.at(-1)?.t || 0,
  );
  const displayed = right.episode ? reducedSample : sourceSample;
  const observed = Object.entries(displayed.sample?.bodies || {});
  const baselineBody = (right.episode ? rightSamples : leftSamples)[0]?.bodies
    .protected;
  const protectedNow = displayed.sample?.bodies.protected;
  const drift =
    baselineBody && protectedNow
      ? Math.hypot(
          ...protectedNow.position.map((v, i) => v - baselineBody.position[i]),
        ) * 1000
      : undefined;
  const contacts = displayed.sample?.contacts || [];
  const interpolation =
    sourceSample.alpha > 0.001 && sourceSample.alpha < 0.999;
  return (
    <section
      className={`replay-instrument ${compact ? "replay-compact" : ""}`}
      aria-label={
        leftRecorded && rightRecorded
          ? "Synchronized failure replay"
          : "Measured simulation comparison"
      }
    >
      <header className="instrument-toolbar">
        <div className="instrument-title">
          <span className="crosshair-mark" aria-hidden="true">
            <Crosshair size={17} />
          </span>
          <span>Failure microscope</span>
          <span className="toolbar-separator" />
          <span className="muted">
            {leftRecorded && rightRecorded
              ? "A ↔ B synchronized"
              : leftRecorded || rightRecorded
                ? "Replay / final state"
                : "Measured final states"}
          </span>
        </div>
        <div className="instrument-actions">
          <button
            className={`icon-button ${trajectory ? "is-active" : ""}`}
            aria-pressed={trajectory}
            aria-label="Toggle measured trajectory"
            onClick={() => setTrajectory((v) => !v)}
          >
            <Layers3 size={16} />
          </button>
          <div className="camera-switch" aria-label="Replay view">
            <button
              className={camera !== "top" ? "selected" : ""}
              onClick={() => onCamera("perspective")}
              aria-pressed={camera !== "top"}
            >
              3D
            </button>
            <button
              className={camera === "top" ? "selected" : ""}
              onClick={() => onCamera("top")}
              aria-pressed={camera === "top"}
            >
              Top
            </button>
          </div>
          <button
            className="icon-button"
            onClick={() => setObjectsOpen(true)}
            aria-label="Inspect measured objects"
          >
            <Box size={17} />
          </button>
        </div>
      </header>
      <div className="scene-pair">
        <ScenePane
          episode={left.episode}
          loading={!!sourceId && !left.episode && !left.error}
          error={left.error}
          retry={left.retry}
          label={leftLabel}
          kind="source"
          time={time}
          camera={camera}
          trajectory={trajectory}
          playing={playing}
          selected={selected}
          onSelect={(name) => {
            setSelected(name);
            setObjectsOpen(true);
          }}
        />
        <ScenePane
          episode={right.episode}
          loading={!!minimizedId && !right.episode && !right.error}
          error={right.error}
          retry={right.retry}
          label={rightLabel}
          kind="reduced"
          time={time}
          camera={camera}
          trajectory={trajectory}
          playing={playing}
          selected={selected}
          onSelect={(name) => {
            setSelected(name);
            setObjectsOpen(true);
          }}
        />
      </div>
      <div
        className="replay-controls"
        ref={playbackRef}
        tabIndex={0}
        role="group"
        aria-label={
          shortcutsEnabled
            ? "Playback. Space plays or pauses; arrow keys step authoritative samples."
            : "Playback. Keyboard shortcuts disabled; use the labeled controls."
        }
        onKeyDown={(e) => {
          if (!shortcutsEnabled || e.target !== e.currentTarget) return;
          if (e.key === " ") {
            e.preventDefault();
            toggle();
          }
          if (e.key === "ArrowLeft") {
            e.preventDefault();
            step(-1);
          }
          if (e.key === "ArrowRight") {
            e.preventDefault();
            step(1);
          }
        }}
      >
        <div className="playback-buttons">
          <button
            className="icon-button"
            aria-label="Restart replay"
            disabled={!duration}
            onClick={() => {
              setTime(0);
              setPlaying(false);
            }}
          >
            <RotateCcw size={15} />
          </button>
          <button
            className="icon-button"
            aria-label="Previous authoritative sample"
            disabled={!duration}
            onClick={() => step(-1)}
          >
            <SkipBack size={15} />
          </button>
          <button
            className="play-button"
            aria-label={playing ? "Pause replay" : "Play replay"}
            disabled={!duration}
            onClick={toggle}
          >
            {playing ? (
              <Pause size={16} fill="currentColor" />
            ) : (
              <Play size={16} fill="currentColor" />
            )}
          </button>
          <button
            className="icon-button"
            aria-label="Next authoritative sample"
            disabled={!duration}
            onClick={() => step(1)}
          >
            <SkipForward size={15} />
          </button>
        </div>
        <span className="playback-time mono">
          {fixed(time, 2)}
          <span> / {fixed(duration, 2)} s</span>
        </span>
        <input
          className="timeline-slider"
          type="range"
          min="0"
          max={duration || 1}
          step="0.001"
          value={Math.min(time, duration)}
          disabled={!duration}
          aria-label="Replay simulation time in seconds"
          aria-valuetext={`${fixed(time, 2)} seconds`}
          onChange={(e) => {
            setPlaying(false);
            setTime(Number(e.target.value));
          }}
          style={
            {
              "--progress": `${duration ? (time / duration) * 100 : 0}%`,
            } as React.CSSProperties
          }
        />
        <button
          className="speed-button"
          aria-label={`Playback speed ${speed} times`}
          onClick={() => setSpeed((s) => (s === 1 ? 0.5 : s === 0.5 ? 2 : 1))}
        >
          {speed}×<ChevronDown size={12} />
        </button>
      </div>
      <div className="trace-caption">
        <span>
          <span className="tiny-cross">+</span>
          {!duration
            ? "Measured final state · no recorded motion trace"
            : interpolation
              ? "Visual interpolation between authoritative samples"
              : "Authoritative sampled frame"}
        </span>
        {playing && camera !== "top" ? (
          <span className="render-quality">Playback · reduced graphics</span>
        ) : null}
        <span className="mono">
          {str(record(left.episode?.trace).frame_rate_hz, "—")} Hz trace · world
          SI
        </span>
        <button
          className="playback-keys"
          onClick={() => {
            setPlaying(false);
            setKeyboardHelp(true);
          }}
        >
          Playback keys
        </button>
      </div>
      {(left.episode && !leftRecorded) || (right.episode && !rightRecorded) ? (
        <p className="endpoint-notice">
          A pane has endpoint states only. It displays the measured final state;
          motion is unavailable for that episode.
        </p>
      ) : null}
      {!compact ? (
        <div className="telemetry-strip">
          <div>
            <span className="telemetry-icon">
              <ArrowDownRight size={16} />
            </span>
            <div>
              <span>Payload height</span>
              <strong className="mono">
                {displayed.sample?.bodies.payload
                  ? fixed(displayed.sample.bodies.payload.position[2] * 100, 2)
                  : "—"}
                <small> cm</small>
              </strong>
            </div>
            {(right.episode ? rightRecorded : leftRecorded) ? (
              <MiniTelemetry
                samples={right.episode ? rightSamples : leftSamples}
                time={time}
                body="payload"
              />
            ) : null}
          </div>
          <div>
            <span className="telemetry-icon">
              <Crosshair size={16} />
            </span>
            <div>
              <span>Protected displacement</span>
              <strong className="mono">
                {fixed(drift, 2)}
                <small> mm</small>
              </strong>
            </div>
          </div>
          <div>
            <span className="telemetry-icon">
              <View size={16} />
            </span>
            <div>
              <span>Active contact pairs</span>
              <strong className="mono">
                {displayed.sample ? contacts.length : "—"}
                <small> pairs</small>
              </strong>
            </div>
          </div>
        </div>
      ) : null}
      {keyboardHelp ? (
        <Drawer
          title="Keyboard playback"
          eyebrow="MEASURED SIMULATION EVIDENCE"
          onClose={() => setKeyboardHelp(false)}
        >
          <p className="drawer-intro">
            Focus the playback control group to use these shortcuts. The arrows
            step through authoritative samples; the timeline can also select an
            interpolated visual frame.
          </p>
          <dl className="definition-list">
            <div>
              <dt>Play or pause</dt>
              <dd>
                <kbd>Space</kbd>
              </dd>
            </div>
            <div>
              <dt>Previous recorded sample</dt>
              <dd>
                <kbd>←</kbd>
              </dd>
            </div>
            <div>
              <dt>Next recorded sample</dt>
              <dd>
                <kbd>→</kbd>
              </dd>
            </div>
          </dl>
          <label className="shortcut-toggle">
            <input
              type="checkbox"
              checked={shortcutsEnabled}
              onChange={(e) => setShortcutsEnabled(e.target.checked)}
            />
            Enable playback shortcuts
          </label>
          <p className="field-help">
            Playback starts only when requested. Reduced-motion preferences are
            respected.
          </p>
        </Drawer>
      ) : null}
      {objectsOpen ? (
        <Drawer
          title="Measured object state"
          eyebrow={`SIMULATION SAMPLE · ${fixed(displayed.sample?.t, 3)} S`}
          onClose={() => setObjectsOpen(false)}
        >
          <p className="drawer-intro">
            Authoritative body poses at the preceding recorded sample. Values
            are in the world frame; SI meters and WXYZ quaternions.
          </p>
          <div className="object-selector">
            {observed.map(([name]) => (
              <button
                key={name}
                className={selected === name ? "selected" : ""}
                onClick={() => setSelected(name)}
              >
                {human(name)}
              </button>
            ))}
          </div>
          <DataDetails value={displayed.sample?.bodies[selected]} />
          <h3 className="spaced-heading">Contacts at this sample</h3>
          {contacts.length ? (
            <DataDetails
              value={Object.fromEntries(
                contacts.map((c, i) => [`Contact ${i + 1}`, c]),
              )}
            />
          ) : (
            <p className="muted">No contact pairs at this sample.</p>
          )}
          <JsonDetails
            value={displayed.sample?.raw}
            label="Complete authoritative sample"
          />
        </Drawer>
      ) : null}
    </section>
  );
}
function MiniTelemetry({
  samples,
  time,
  body,
}: {
  samples: Sample[];
  time: number;
  body: string;
}) {
  const vals = samples
    .map((s) => ({ t: s.t, z: s.bodies[body]?.position[2] }))
    .filter((p): p is { t: number; z: number } => p.z !== undefined);
  if (!vals.length) return null;
  const min = Math.min(...vals.map((p) => p.z));
  const max = Math.max(...vals.map((p) => p.z));
  const duration = vals.at(-1)?.t || 1;
  const points = vals
    .filter((_, i) => i % Math.max(1, Math.floor(vals.length / 100)) === 0)
    .map(
      (p) =>
        `${(p.t / duration) * 100},${28 - ((p.z - min) / (max - min || 1)) * 24}`,
    )
    .join(" ");
  return (
    <svg className="mini-telemetry" viewBox="0 0 100 32" aria-hidden="true">
      <polyline
        points={points}
        fill="none"
        stroke="#75dce9"
        strokeWidth="1.2"
      />
      <line
        x1={(time / duration) * 100}
        x2={(time / duration) * 100}
        y1="0"
        y2="32"
        stroke="#c4b5fd"
        strokeWidth=".7"
      />
    </svg>
  );
}
export function EpisodeDrawer({
  id,
  onClose,
}: {
  id: string;
  onClose: () => void;
}) {
  const { episode, error, retry } = useEpisode(id);
  const samples = useMemo(() => samplesOf(episode), [episode]);
  const [index, setIndex] = useState(0);
  const sample = samples[Math.min(index, samples.length - 1)];
  return (
    <Drawer title="Episode evidence" eyebrow={id} onClose={onClose} wide>
      {error ? (
        <ErrorMessage error={error} retry={retry} />
      ) : !episode ? (
        <Loading />
      ) : (
        <>
          <div className="episode-summary-line">
            <Status value={episodeVerdict(episode)} />
            <span className="mono">
              {str(episode.policy_id ?? record(episode.policy).policy_id)}
            </span>
            <span className="muted">Simulation only</span>
          </div>
          <OracleSummary
            episode={episode}
            onContactTime={(t) => {
              const at = sampleAt(samples, t);
              setIndex(
                Math.min(
                  samples.length - 1,
                  at.index + (at.sample && at.sample.t < t ? 1 : 0),
                ),
              );
              requestAnimationFrame(() =>
                document
                  .querySelector(".sample-seeker")
                  ?.scrollIntoView({ block: "start" }),
              );
            }}
          />
          <JsonDetails
            value={episode.metrics}
            label="Complete metrics · raw SI units"
          />
          <JsonDetails
            value={episode.scenario}
            label="Immutable scene parameters"
          />
          <JsonDetails
            value={episode.oracle}
            label="Task oracle verdict and thresholds"
          />
          <h3 className="spaced-heading">Authoritative samples</h3>
          <div className="sample-seeker">
            <label htmlFor="sample-seek">
              Sample {index + 1} of {samples.length} · {fixed(sample?.t, 3)} s
            </label>
            <input
              id="sample-seek"
              type="range"
              min="0"
              max={Math.max(0, samples.length - 1)}
              value={index}
              onChange={(e) => setIndex(Number(e.target.value))}
            />
          </div>
          <div className="table-scroll" tabIndex={0}>
            <table>
              <caption className="sr-only">
                Body positions at sample {index + 1}, meters in world
                coordinates
              </caption>
              <thead>
                <tr>
                  <th>Object</th>
                  <th>X · m</th>
                  <th>Y · m</th>
                  <th>Z · m</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(sample?.bodies || {}).map(([name, p]) => (
                  <tr key={name}>
                    <th>{human(name)}</th>
                    {p.position.map((v, i) => (
                      <td key={i} className="mono">
                        {fixed(v, 4)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <JsonDetails value={sample?.raw} label="Sample data and contacts" />
          <div className="artifact-footnote">
            <span>Artifact SHA-256</span>
            <span className="mono">
              {shortHash(episode.artifact_sha ?? episode.hash)}
            </span>
            {episode.artifact_sha ? (
              <a
                className="text-button"
                href={`/api/artifacts/${episode.artifact_sha}`}
                target="_blank"
                rel="noreferrer"
              >
                Open verified artifact
                <Maximize2 size={13} />
              </a>
            ) : null}
          </div>
        </>
      )}
    </Drawer>
  );
}
function OracleSummary({
  episode,
  onContactTime,
}: {
  episode: Episode;
  onContactTime: (t: number) => void;
}) {
  const metrics = episode.metrics || {};
  const oracle = record(episode.oracle);
  const checks = record(oracle.components);
  const thresholds = record(oracle.thresholds);
  const measure = (
    value: unknown,
    multiplier: number,
    digits: number,
    unit: string,
  ) =>
    typeof value === "number"
      ? `${fixed(value * multiplier, digits)} ${unit}`
      : "Not recorded";
  const rows = [
    {
      key: "inside_target",
      label: "Payload containment",
      value:
        typeof checks.inside_target === "boolean"
          ? checks.inside_target
            ? "Inside target"
            : "Outside target"
          : "Not recorded",
      rule: "All oriented corners inside bay",
    },
    {
      key: "released",
      label: "Final gripper opening",
      value: measure(metrics.final_gripper_opening, 1000, 1, "mm"),
      rule: `≥ ${measure(thresholds.released_opening_min, 1000, 1, "mm")}`,
    },
    {
      key: "stable",
      label: "Settled duration",
      value: measure(metrics.stable_duration, 1, 2, "s"),
      rule: `≥ ${measure(thresholds.stable_duration_min, 1, 2, "s")}`,
    },
    {
      key: "lifted",
      label: "Maximum payload height",
      value: measure(metrics.max_payload_height, 1000, 1, "mm"),
      rule: `≥ ${measure(thresholds.payload_center_lift_min, 1000, 1, "mm")}`,
    },
    {
      key: "protected_position",
      label: "Maximum protected drift",
      value: measure(metrics.protected_max_displacement, 1000, 2, "mm"),
      rule: `≤ ${measure(thresholds.protected_displacement_max, 1000, 1, "mm")}`,
    },
    {
      key: "protected_orientation",
      label: "Maximum protected tilt",
      value: measure(metrics.protected_max_angle, 180 / Math.PI, 2, "°"),
      rule: `≤ ${measure(thresholds.protected_angle_max, 180 / Math.PI, 2, "°")}`,
    },
    {
      key: "no_forbidden_contact",
      label: "Peak forbidden contact force",
      value: measure(metrics.peak_forbidden_normal_force, 1, 2, "N"),
      rule: `No protected-object contact > ${measure(thresholds.forbidden_contact_force_min, 1, 2, "N")}`,
    },
  ];
  const violation = record(metrics.first_violation);
  return (
    <section className="oracle-summary">
      <div className="oracle-summary-heading">
        <div>
          <h3>{human(episode.terminal_reason ?? episodeVerdict(episode))}</h3>
          <p>
            Measured at every physics step against the frozen task thresholds.
          </p>
        </div>
        <span className="mono">
          {measure(metrics.duration, 1, 2, "s")} episode
        </span>
      </div>
      {typeof violation.time === "number" ? (
        <div className="contact-callout">
          <div>
            <strong>
              First forbidden contact · {fixed(violation.time, 3)} s
            </strong>
            <p>
              {human(violation.geom1)} ↔ {human(violation.geom2)} ·{" "}
              {measure(violation.normal_force, 1, 2, "N")} normal force
            </p>
          </div>
          <button
            className="text-button"
            onClick={() => onContactTime(num(violation.time))}
          >
            Inspect first replay frame after contact
          </button>
        </div>
      ) : null}
      <div className="table-scroll" tabIndex={0}>
        <table>
          <caption className="sr-only">
            Physics oracle checks with measured values, registered thresholds,
            and verdicts
          </caption>
          <thead>
            <tr>
              <th>Task check</th>
              <th>Measured</th>
              <th>Registered rule</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key}>
                <th>{row.label}</th>
                <td className="mono">{row.value}</td>
                <td className="oracle-rule">{row.rule}</td>
                <td>
                  <Status
                    value={
                      typeof checks[row.key] === "boolean"
                        ? checks[row.key]
                          ? "pass"
                          : "fail"
                        : "pending"
                    }
                    label={
                      typeof checks[row.key] === "boolean"
                        ? checks[row.key]
                          ? "Pass"
                          : "Violation"
                        : "Pending"
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
