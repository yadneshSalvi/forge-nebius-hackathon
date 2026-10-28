export type Dict = Record<string, unknown>;
export type View =
  "workcell" | "campaigns" | "failures" | "curricula" | "policies" | "reports";
export type Vec3 = [number, number, number];
export interface CampaignSummary {
  id: string;
  name: string;
  status: string;
  stage: string;
  created_at: string;
  updated_at: string;
  generation: number;
  progress: { completed: number; total: number; message: string };
  recorded: boolean;
  config: Dict;
  error?: unknown;
}
export interface EpisodeSummary {
  id: string;
  outcome?: string | Dict;
  policy_id?: string;
  scenario?: Dict;
  metrics?: Dict;
  family?: string;
  stage?: string;
  [key: string]: unknown;
}
export interface ReductionStep {
  factor: string;
  from_value: unknown;
  to_value: unknown;
  accepted: boolean;
  failure_count: number;
  valid_count: number;
  episode_ids: string[];
  kind: string;
}
export interface Counterexample {
  secondary_boundaries?: Counterexample[];
  label?: string;
  reason?: string;
  failure_reason?: string;
  source_episode_id: string;
  minimized_episode_id: string;
  source_params: Dict;
  minimized_params: Dict;
  steps: ReductionStep[];
  confirmation: {
    failures: number;
    total: number;
    interval?: unknown;
    episode_ids: string[];
  };
  locality: unknown;
  changed_before: number;
  changed_after: number;
  magnitude_before: number;
  magnitude_after: number;
}
export interface CurriculumArm {
  cluster_allocation?: number[] | Record<string, number>;
  name: string;
  label: string;
  demo_ids: string[];
  accepted: number;
  rejected: number;
  retained_nominal: number;
  corrective: number;
  acquisition_episodes: number;
}
export interface Demonstration {
  id: string;
  episode_id: string | null;
  arm: string;
  split: string;
  source: string;
  success: boolean;
  trajectory_sha: string;
}
export interface Curriculum {
  failure_clusters?: unknown[];
  design?: unknown;
  paired_acquisition_sha?: string;
  id: string;
  base_checkpoint_sha: string;
  arms: CurriculumArm[];
  demonstrations: Demonstration[];
  excluded_splits: string[];
  training_budget: unknown;
  status: string;
}
export interface TrainingRun {
  arm: string;
  seed: number;
  checkpoint_sha: string;
  base_checkpoint_sha: string;
  examples: number;
  steps: number;
  initial_loss: number;
  final_loss: number;
  elapsed_seconds: number;
  weight_change_l2: number;
}
export interface Training {
  status: string;
  runs: TrainingRun[];
}
export interface ReportArm {
  name: string;
  label: string;
  successes: number;
  total: number;
  rate: number;
  interval?: unknown;
  delta: number;
  delta_interval?: unknown;
  nominal?: Dict;
  shifted?: Dict;
  paired: {
    rescued: number;
    regressed: number;
    both_success: number;
    both_failure: number;
  };
  seeds?: unknown[];
  families?: Dict[];
  [key: string]: unknown;
}
export interface Report {
  id: string;
  label: string;
  scope: unknown;
  decision: string;
  decision_reasons: string[];
  manifest_sha: string;
  protocol_sha: string;
  baseline: { successes: number; total: number; rate: number };
  arms: ReportArm[];
  selected_arm: string;
  regressions: Dict[];
  limitations: string[];
  resources: unknown;
  [key: string]: unknown;
}
export interface ModelEvidence {
  planner?: Dict;
  visual?: Dict;
}
export interface Campaign extends CampaignSummary {
  events: Dict[];
  episodes: EpisodeSummary[];
  counterexample?: Counterexample | null;
  curriculum?: Curriculum | null;
  training?: Training | null;
  report?: Report | null;
  registered_report?: Report | null;
  model_evidence?: ModelEvidence;
  artifacts?: unknown[];
  [key: string]: unknown;
}
export interface Bootstrap {
  task: Dict;
  runtime: Dict;
  campaigns: CampaignSummary[];
  selected_campaign_id?: string;
  providers: unknown;
  policies: Dict[];
  base_ready?: boolean;
  protocol?: Dict;
  protocol_sha?: string;
}
export interface Pose {
  position: Vec3;
  quaternion: [number, number, number, number];
}
export interface Sample {
  t: number;
  bodies: Record<string, Pose>;
  values: Dict;
  contacts: Dict[];
  raw: Dict;
}
export interface Geometry {
  name: string;
  body: string;
  type: string;
  size: Vec3;
  position: Vec3;
  quaternion: [number, number, number, number];
  rgba?: [number, number, number, number];
  raw: Dict;
}
export interface Episode extends EpisodeSummary {
  trace?: unknown;
  geometry?: unknown;
  hash?: string;
  artifact_sha?: string;
}
