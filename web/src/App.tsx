import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowUpRight,
  Box,
  ChevronRight,
  FileText,
  FlaskConical,
  Focus,
  GitBranch,
  Layers3,
  Menu,
  Plus,
  RefreshCw,
  SquareDashed,
  X,
} from "lucide-react";
import { useForge, useLocationState } from "./api";
import { Campaigns } from "./Campaigns";
import { activeStatus, fixed, human, record, shortHash, str } from "./data";
import { Curricula, Policies } from "./Learning";
import { LaunchDrawer, ProviderList, TrainingDrawer } from "./LaunchDrawer";
import { EpisodeDrawer } from "./Replay";
import { Reports } from "./Reports";
import { DefinitionList, Drawer, Eyebrow, JsonDetails, Status } from "./ui";
import { Failures, Workcell } from "./Workcell";
import type { Campaign, View } from "./types";
import { Empty, Loading, PageHeading } from "./ui";

const navigation = [
  { view: "workcell", label: "Workcell", icon: Box },
  { view: "campaigns", label: "Campaigns", icon: FlaskConical },
  { view: "failures", label: "Failures", icon: Focus },
  { view: "curricula", label: "Curricula", icon: Layers3 },
  { view: "policies", label: "Policies", icon: GitBranch },
  { view: "reports", label: "Reports", icon: FileText },
] as const;
export default function App() {
  const [location, navigate] = useLocationState();
  const { bootstrap, campaign, networkError, lastSync, loading, refresh } =
    useForge(location.campaign, (id) => navigate({ campaign: id }, true));
  const [drawer, setDrawer] = useState<
    "launch" | "training" | "task" | "providers" | null
  >(null);
  const [mobileNav, setMobileNav] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);
  const menuRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 520px)");
    const update = () => {
      if (!media.matches) setMobileNav(false);
    };
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!mobileNav) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebarRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setMobileNav(false);
      }
      if (event.key !== "Tab") return;
      const buttons = [
        ...(sidebarRef.current?.querySelectorAll<HTMLButtonElement>(
          "button:not(:disabled)",
        ) || []),
      ].filter((button) => button.getClientRects().length);
      const first = buttons[0];
      const last = buttons.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", handleKey);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKey);
      menuRef.current?.focus();
    };
  }, [mobileNav]);
  const activeJobs =
    bootstrap?.campaigns.filter((c) => activeStatus(c.status)).length || 0;
  const currentNav = navigation.find((n) => n.view === location.view)!;
  const task = bootstrap?.task || {};
  const runtime = bootstrap?.runtime || {};
  const onView = (view: View) => {
    navigate({ view, episode: "" });
    setMobileNav(false);
    window.scrollTo({ top: 0, behavior: "instant" });
  };
  const onEpisode = (id: string) => {
    if (id) navigate({ episode: id });
  };
  const onCamera = (camera: string) => navigate({ camera }, true);
  const onBoundary = (index: number) =>
    navigate({ boundary: String(index), episode: "" }, true);
  const onCreated = (created: Campaign) => {
    setDrawer(null);
    navigate({
      campaign: created.id,
      view: "campaigns",
      episode: "",
      boundary: "0",
    });
    refresh();
  };
  const onChallenge = (created: Campaign) => {
    navigate({
      campaign: created.id,
      view: "policies",
      episode: "",
      boundary: "0",
    });
    refresh();
    window.scrollTo({ top: 0, behavior: "instant" });
  };
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to evidence
      </a>
      <aside
        id="primary-navigation"
        ref={sidebarRef}
        className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}
        aria-label="Primary navigation"
        role={mobileNav ? "dialog" : undefined}
        aria-modal={mobileNav ? true : undefined}
      >
        <div className="brand">
          <ForgeMark />
          <span>FORGE</span>
          <small>LAB / 01</small>
          <button
            className="icon-button mobile-nav-close"
            aria-label="Close navigation"
            onClick={() => setMobileNav(false)}
          >
            <X size={19} />
          </button>
        </div>
        <div className="workspace-caption">
          <span className="workspace-led" />
          PHYSICAL AI WORKSPACE
        </div>
        <nav>
          {navigation.map((n, i) => (
            <button
              key={n.view}
              onClick={() => onView(n.view)}
              aria-label={n.label}
              aria-current={location.view === n.view ? "page" : undefined}
              className={
                location.view === n.view ? "nav-item selected" : "nav-item"
              }
            >
              <n.icon size={18} />
              <span>{n.label}</span>
              <small className="mono">0{i + 1}</small>
              {location.view === n.view ? (
                <span className="nav-active-mark" />
              ) : null}
            </button>
          ))}
        </nav>
        <div className="sidebar-project">
          <Eyebrow>REGISTERED EMBODIMENT</Eyebrow>
          <div className="gantry-glyph" aria-hidden="true">
            <svg viewBox="0 0 160 64">
              <path
                d="M20 51V13h120v38M15 51h10m110 0h10M40 13v7h80v-7M80 20v16m-12 0h24M71 36v11h7m11-11v11h-7"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.3"
              />
              <path d="M51 55h60" stroke="currentColor" strokeDasharray="2 4" />
            </svg>
          </div>
          <strong>Cartesian gantry</strong>
          <span>Original geometry · 3-axis</span>
          <button
            className="text-button"
            onClick={() => {
              setMobileNav(false);
              setDrawer("task");
            }}
          >
            Inspect task
            <ArrowUpRight size={12} />
          </button>
        </div>
        <div className="sidebar-bottom">
          <button
            className="model-routing-button"
            onClick={() => {
              setMobileNav(false);
              setDrawer("providers");
            }}
          >
            <span className="nvidia-letter">N</span>
            <span>
              <strong>NVIDIA reasoning</strong>
              <small>Measured by physics</small>
            </span>
            <ArrowUpRight size={13} />
          </button>
          <div className="local-environment">
            <span
              className={`connection-led ${networkError ? "disconnected" : ""}`}
            />
            <span>
              {networkError ? "Connection interrupted" : "Local environment"}
            </span>
            <span className="mono">v1.0</span>
          </div>
        </div>
      </aside>
      {mobileNav ? (
        <button
          className="navigation-scrim"
          aria-label="Close navigation"
          onClick={() => setMobileNav(false)}
        />
      ) : null}
      <div className="application-main" inert={mobileNav}>
        <header className="topbar">
          <div className="topbar-breadcrumb">
            <button
              className="icon-button mobile-menu"
              ref={menuRef}
              aria-label="Open navigation"
              aria-expanded={mobileNav}
              aria-controls="primary-navigation"
              onClick={() => setMobileNav(true)}
            >
              <Menu size={19} />
            </button>
            <span className="workspace-symbol">
              <SquareDashed size={18} />
            </span>
            <span className="project-name">Kitting workcell</span>
            <ChevronRight size={12} />
            <span>{currentNav.label}</span>
          </div>
          <div className="topbar-right">
            <div className="simulation-badge">
              <span className="simulation-shape" />
              SIMULATION ONLY
            </div>
            <button
              className="button button-small button-quiet topbar-launch"
              onClick={() => setDrawer("launch")}
            >
              <Plus size={14} />
              New campaign
            </button>
            <button
              className="avatar-button"
              aria-label="Inspect local runtime"
              onClick={() => setDrawer("task")}
            >
              L<span />
            </button>
          </div>
        </header>
        {networkError ? (
          <div className="network-banner" role="alert">
            <span>
              <Activity size={16} />
              <strong>Connection interrupted.</strong> Showing the last received
              evidence.
            </span>
            <button onClick={refresh}>
              <RefreshCw size={14} />
              Reconnect
            </button>
            <details>
              <summary>Details</summary>
              <span>{networkError}</span>
            </details>
          </div>
        ) : null}
        <main
          id="main-content"
          className={`content content-${location.view}`}
          tabIndex={-1}
        >
          {campaign ? (
            <div className="active-campaign-strip">
              <span
                className={`campaign-mode ${campaign.recorded ? "recorded" : "live"}`}
              >
                <span />
                {campaign.recorded ? "RECORDED CAMPAIGN" : "LIVE CAMPAIGN"}
              </span>
              <select
                aria-label="Selected campaign"
                value={campaign.id}
                onChange={(e) =>
                  navigate({ campaign: e.target.value, episode: "" })
                }
              >
                {bootstrap?.campaigns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
              <span className="campaign-strip-divider" />
              <Status value={campaign.status} />
              <span className="mono active-campaign-id">
                {campaign.id.slice(-12)}
              </span>
            </div>
          ) : (
            <div className="active-campaign-strip">
              <span className="campaign-mode">
                <span />
                {loading
                  ? "CONNECTING TO LOCAL RUNTIME"
                  : bootstrap?.base_ready
                    ? "READY FOR A CAMPAIGN"
                    : "PREPARING LOCAL CHECKPOINT"}
              </span>
              <span className="mono active-campaign-id">
                {bootstrap
                  ? `MuJoCo ${str(runtime.mujoco)} · ${str(runtime.device)}`
                  : "Authoritative simulation evidence"}
              </span>
            </div>
          )}
          {!campaign && (loading || !!location.campaign) && !networkError ? (
            <>
              <PageHeading
                number="…"
                label={currentNav.label}
                title="Loading campaign evidence."
                description="Fetching the immutable campaign, measured outcomes, and registered report."
              />
              <Loading label="Reading the local evidence store" />
            </>
          ) : !campaign && location.campaign && networkError ? (
            <Empty
              title="Campaign evidence is unavailable"
              action={
                <button className="button button-quiet" onClick={refresh}>
                  Reconnect
                </button>
              }
            >
              {networkError}
            </Empty>
          ) : location.view === "workcell" ? (
            <Workcell
              campaign={campaign}
              camera={location.camera}
              onCamera={onCamera}
              navigate={onView}
              onLaunch={() => setDrawer("launch")}
              onEpisode={onEpisode}
              onTask={() => setDrawer("task")}
              baseReady={!!bootstrap?.base_ready}
              connecting={loading}
              boundary={location.boundary}
              onBoundary={onBoundary}
            />
          ) : location.view === "campaigns" ? (
            <Campaigns
              campaign={campaign}
              campaigns={bootstrap?.campaigns || []}
              onSelect={(id) => navigate({ campaign: id, episode: "" })}
              onLaunch={() => setDrawer("launch")}
              onEpisode={onEpisode}
              onRefresh={refresh}
              onInspect={() => onView("failures")}
            />
          ) : location.view === "failures" ? (
            <Failures
              campaign={campaign}
              camera={location.camera}
              onCamera={onCamera}
              onEpisode={onEpisode}
              onCurriculum={() => onView("curricula")}
              boundary={location.boundary}
              onBoundary={onBoundary}
            />
          ) : location.view === "curricula" ? (
            <Curricula
              campaign={campaign}
              onTrain={() => setDrawer("training")}
              onEpisode={onEpisode}
            />
          ) : location.view === "policies" ? (
            <Policies
              campaign={campaign}
              bootstrap={bootstrap}
              camera={location.camera}
              onCamera={onCamera}
              onTrain={() => setDrawer("training")}
              onEpisode={onEpisode}
              onChallenge={onChallenge}
              onParent={(id) => navigate({ campaign: id, view: "policies" })}
            />
          ) : (
            <Reports
              campaign={campaign}
              bootstrap={bootstrap}
              onPolicies={() => onView("policies")}
              onEpisode={onEpisode}
            />
          )}
        </main>
        <footer className="global-status">
          <div>
            <span
              className={`connection-led ${networkError ? "disconnected" : ""}`}
            />
            <span>
              {networkError
                ? "Offline · last good evidence retained"
                : loading
                  ? "Connecting"
                  : "Local runtime connected"}
            </span>
            <span className="footer-separator">/</span>
            <span className="mono">
              {bootstrap
                ? `MuJoCo ${str(runtime.mujoco)} · ${str(runtime.device)}`
                : "ENGINE PENDING"}
            </span>
          </div>
          <div>
            <span>
              {activeJobs} active {activeJobs === 1 ? "job" : "jobs"}
            </span>
            <span className="footer-separator">/</span>
            <span className="mono">
              SYNC{" "}
              {lastSync
                ? lastSync.toLocaleTimeString([], {
                    hour12: false,
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })
                : "—"}
            </span>
          </div>
        </footer>
      </div>
      {drawer === "launch" ? (
        <LaunchDrawer
          bootstrap={bootstrap}
          onClose={() => setDrawer(null)}
          onCreated={onCreated}
        />
      ) : drawer === "training" && campaign ? (
        <TrainingDrawer
          campaign={campaign}
          onClose={() => setDrawer(null)}
          onStarted={() => {
            setDrawer(null);
            onView("policies");
            refresh();
          }}
        />
      ) : drawer === "providers" ? (
        <Drawer
          title="Configured model routes"
          eyebrow="ACTUAL PROVIDERS / VISIBLE QUALIFICATION"
          onClose={() => setDrawer(null)}
        >
          <p className="drawer-intro">
            NVIDIA models propose bounded experiments and interpret simulation
            artifacts. The physics oracle computes success and failure. Every
            actual request retains its provider receipt.
          </p>
          <ProviderList providers={bootstrap?.providers} />
        </Drawer>
      ) : drawer === "task" ? (
        <Drawer
          title="Cartesian kit transfer"
          eyebrow="REGISTERED TASK / LOCAL SIMULATION"
          onClose={() => setDrawer(null)}
        >
          <div className="task-drawer-illustration" aria-hidden="true">
            <ForgeMark />
            <span>PLACE. RELEASE. PROTECT.</span>
          </div>
          <p className="drawer-intro">
            {str(
              task.success_predicate,
              "Move the payload into the target bay, release it, and preserve the neighboring protected object.",
            )}
          </p>
          <DefinitionList
            entries={[
              ["Embodiment", human(task.embodiment)],
              ["Task revision", str(task.revision)],
              [
                "Task SHA-256",
                <span className="mono">
                  {shortHash(str(task.task_spec_hash, ""))}
                </span>,
              ],
              [
                "Simulation step",
                `${fixed(Number(record(task.physics).timestep) * 1000, 1)} ms`,
              ],
              [
                "Protected movement limit",
                `${fixed(Number(record(task.thresholds).protected_displacement_max) * 1000, 1)} mm`,
              ],
              ["Policy", str(task.policy_kind)],
              ["Asset license", str(task.asset_license)],
            ]}
          />
          <JsonDetails value={task} label="Full frozen task specification" />
          <JsonDetails
            value={bootstrap?.protocol}
            label="Development protocol and release gate"
          />
          <JsonDetails
            value={runtime}
            label="Pinned runtime and qualifications"
          />
        </Drawer>
      ) : null}
      {location.episode ? (
        <EpisodeDrawer
          id={location.episode}
          onClose={() => navigate({ episode: "" }, true)}
        />
      ) : null}
    </div>
  );
}
function ForgeMark() {
  return (
    <svg className="forge-mark" viewBox="0 0 32 32" aria-hidden="true">
      <path
        d="M5 26V6h23M5 16h18M14 26V6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.3"
      />
      <path d="m25 22 4 3-4 3" fill="none" stroke="#c4b5fd" strokeWidth="1.8" />
    </svg>
  );
}
