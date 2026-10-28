import type {
  Dict,
  Episode,
  EpisodeSummary,
  Geometry,
  Pose,
  Sample,
  Vec3,
} from "./types";

export const record = (value: unknown): Dict =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Dict)
    : {};
export const array = (value: unknown): unknown[] =>
  Array.isArray(value) ? value : [];
export const str = (value: unknown, fallback = "—"): string =>
  typeof value === "string" && value
    ? value
    : typeof value === "number"
      ? String(value)
      : fallback;
export const num = (value: unknown, fallback = 0): number =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;
export const human = (value: unknown): string =>
  str(value)
    .replaceAll("_", " ")
    .replace(/\b\w/g, (m) => m.toUpperCase());
export const percent = (value: unknown, digits = 0) =>
  typeof value === "number" ? `${(value * 100).toFixed(digits)}%` : "—";
export const shortHash = (value?: string) =>
  value ? `${value.slice(0, 8)}…${value.slice(-4)}` : "Pending";
export const fixed = (value: unknown, digits = 2) =>
  typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "—";
export const formatValue = (value: unknown): string =>
  value == null
    ? "—"
    : typeof value === "number"
      ? Number(value.toFixed(4)).toString()
      : typeof value === "string"
        ? value
        : JSON.stringify(value);
export const textOf = (
  value: unknown,
  fallback = "Awaiting recorded evidence.",
): string =>
  typeof value === "string"
    ? value
    : Array.isArray(value)
      ? value
          .map((v) => textOf(v, ""))
          .filter(Boolean)
          .join(" · ")
      : value && typeof value === "object"
        ? Object.entries(record(value))
            .map(([k, v]) => `${human(k)}: ${formatValue(v)}`)
            .join(" · ")
        : fallback;
export const activeStatus = (status?: string) =>
  [
    "queued",
    "running",
    "planning",
    "discovery",
    "minimization",
    "training",
    "evaluation",
    "pause_requested",
    "cancel_requested",
    "resuming",
  ].includes(status || "");
export const outcome = (value: unknown): string =>
  typeof value === "boolean"
    ? value
      ? "success"
      : "failure"
    : typeof value === "string"
      ? value
      : str(
          record(value).status ??
            record(value).verdict ??
            record(value).terminal_reason ??
            record(value).success,
          "pending",
        );
export const episodeVerdict = (episode?: EpisodeSummary | null): string => {
  if (!episode) return "pending";
  if (episode.valid === false || episode.status === "invalid") return "invalid";
  if (episode.status === "interrupted" || episode.status === "canceled")
    return str(episode.status);
  if (typeof episode.success === "boolean")
    return episode.success ? "success" : "failure";
  return outcome(episode.outcome ?? episode.status);
};
export const paramsOf = (episode?: EpisodeSummary | null): Dict =>
  record(
    episode?.scenario?.parameters ??
      episode?.scenario?.params ??
      episode?.parameters,
  );
export const isSuccess = (value: unknown) =>
  ["success", "passed", "pass", "true"].includes(outcome(value).toLowerCase());
export const tone = (value: unknown): string => {
  const s = str(value, "").toLowerCase();
  if (
    [
      "success",
      "passed",
      "pass",
      "completed",
      "ready",
      "accepted",
      "promote",
      "true",
    ].some((v) => s === v)
  )
    return "pass";
  if (
    [
      "failure",
      "failed",
      "fail",
      "regression",
      "reject",
      "false",
      "protected_contact",
      "collision",
    ].some((v) => s.includes(v))
  )
    return "fail";
  if (
    [
      "pending",
      "uncertain",
      "blocked",
      "paused",
      "invalid",
      "interrupted",
      "inconclusive",
      "cancel",
    ].some((v) => s.includes(v))
  )
    return "warn";
  return "active";
};
const vec = (v: unknown, fallback: Vec3 = [0, 0, 0]): Vec3 =>
  Array.isArray(v) && v.length >= 3
    ? [num(v[0]), num(v[1]), num(v[2])]
    : fallback;
const quat = (v: unknown): [number, number, number, number] =>
  Array.isArray(v) && v.length >= 4
    ? [num(v[0], 1), num(v[1]), num(v[2]), num(v[3])]
    : [1, 0, 0, 0];
const pose = (value: unknown): Pose => {
  const p = record(value);
  return {
    position: vec(p.position ?? p.pos ?? p.xpos ?? value),
    quaternion: quat(p.quaternion ?? p.quat ?? p.xquat),
  };
};
export function samplesOf(episode?: Episode | null): Sample[] {
  if (!episode) return [];
  const trace = record(episode.trace);
  const samples = Array.isArray(episode.trace)
    ? episode.trace
    : array(trace.samples ?? trace.frames ?? trace.states);
  return samples.map((value, index) => {
    const raw = record(value);
    const bodies: Record<string, Pose> = {};
    const bodyData = raw.bodies ?? raw.body_poses ?? raw.poses ?? raw.objects;
    if (Array.isArray(bodyData))
      bodyData.forEach((b, i) => {
        const body = record(b);
        bodies[str(body.name ?? body.id, i.toString())] = pose(body);
      });
    else
      Object.entries(record(bodyData)).forEach(([name, p]) => {
        bodies[name] = pose(p);
      });
    for (const name of [
      "payload",
      "protected",
      "protected_object",
      "gripper",
      "end_effector",
      "tool",
      "carriage",
      "gantry_x",
      "gantry_y",
      "gantry_z",
    ]) {
      if (raw[name]) bodies[name] = pose(raw[name]);
      else if (raw[`${name}_pos`] || raw[`${name}_position`])
        bodies[name] = pose({
          position: raw[`${name}_pos`] ?? raw[`${name}_position`],
          quaternion: raw[`${name}_quat`],
        });
    }
    return {
      t: num(
        raw.t ?? raw.time ?? raw.time_s ?? raw.sim_time,
        index * num(trace.sample_dt, 0.02),
      ),
      bodies,
      values: record(raw.metrics ?? raw.telemetry ?? raw),
      contacts: array(raw.contacts).map(record),
      raw,
    };
  });
}
export function geometryOf(episode?: Episode | null): Geometry[] {
  if (!episode) return [];
  const source = episode.geometry ?? record(episode.scene).geometries;
  const geom = record(source);
  const items = Array.isArray(source)
    ? source
    : array(
        geom.geometries ??
          geom.geoms ??
          geom.objects ??
          geom.bodies ??
          geom.geometry,
      );
  return items.map((item, index) => {
    const g = record(item);
    return {
      name: str(g.name ?? g.id, `geom_${index}`),
      body: str(g.body ?? g.body_name ?? g.name, `geom_${index}`),
      type: str(g.type ?? g.shape, "box"),
      size: vec(g.size ?? g.half_extents ?? g.dimensions),
      position: vec(g.position ?? g.pos ?? g.local_position),
      quaternion: quat(g.quaternion ?? g.quat),
      rgba: Array.isArray(g.rgba) ? (g.rgba as Geometry["rgba"]) : undefined,
      raw: g,
    };
  });
}
export function sampleAt(
  samples: Sample[],
  time: number,
): { sample?: Sample; next?: Sample; alpha: number; index: number } {
  if (!samples.length) return { alpha: 0, index: 0 };
  let lo = 0,
    hi = samples.length - 1;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (samples[mid].t <= time) lo = mid;
    else hi = mid - 1;
  }
  const next = samples[Math.min(lo + 1, samples.length - 1)];
  return {
    sample: samples[lo],
    next,
    alpha:
      next.t > samples[lo].t
        ? Math.max(
            0,
            Math.min(1, (time - samples[lo].t) / (next.t - samples[lo].t)),
          )
        : 0,
    index: lo,
  };
}
export const intervalText = (value: unknown) => {
  if (Array.isArray(value) && value.length >= 2)
    return `${percent(value[0], 1)}–${percent(value[1], 1)}`;
  const r = record(value);
  const low = r.low ?? r.lower ?? r.lower_bound;
  const high = r.high ?? r.upper ?? r.upper_bound;
  return low != null && high != null
    ? `${percent(low, 1)}–${percent(high, 1)}`
    : textOf(value, "Interval pending");
};
export const differenceIntervalText = (value: unknown) => {
  const r = record(value);
  const bounds = Array.isArray(value)
    ? value
    : [r.low ?? r.lower, r.high ?? r.upper];
  if (typeof bounds[0] !== "number" || typeof bounds[1] !== "number")
    return "Interval pending";
  const pp = (v: number) => `${v > 0 ? "+" : ""}${fixed(v * 100, 1)}`;
  return `${pp(bounds[0])} to ${pp(bounds[1])} pp`;
};
