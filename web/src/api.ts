import { useCallback, useEffect, useRef, useState } from "react";
import { activeStatus, record, str } from "./data";
import type { Bootstrap, Campaign, Episode, View } from "./types";

const views: View[] = [
  "workcell",
  "campaigns",
  "failures",
  "curricula",
  "policies",
  "reports",
];
export function readLocation() {
  const q = new URLSearchParams(location.search);
  return {
    view: views.includes(q.get("view") as View)
      ? (q.get("view") as View)
      : ("workcell" as View),
    campaign: q.get("campaign") || "",
    episode: q.get("episode") || "",
    camera: q.get("camera") || "perspective",
    boundary: q.get("boundary") || "0",
  };
}
export function useLocationState() {
  const [state, setState] = useState(readLocation);
  useEffect(() => {
    const listener = () => setState(readLocation());
    addEventListener("popstate", listener);
    return () => removeEventListener("popstate", listener);
  }, []);
  const navigate = useCallback(
    (patch: Partial<ReturnType<typeof readLocation>>, replace = false) => {
      const next = { ...readLocation(), ...patch };
      const q = new URLSearchParams();
      if (next.view !== "workcell") q.set("view", next.view);
      if (next.campaign) q.set("campaign", next.campaign);
      if (next.episode) q.set("episode", next.episode);
      if (next.camera !== "perspective") q.set("camera", next.camera);
      if (next.boundary !== "0") q.set("boundary", next.boundary);
      history[replace ? "replaceState" : "pushState"](
        null,
        "",
        `${location.pathname}${q.size ? `?${q}` : ""}`,
      );
      setState(next);
    },
    [],
  );
  return [state, navigate] as const;
}
export async function request<T>(path: string, options: RequestInit = {}) {
  const response = await fetch(`/api${path}`, options);
  const json = await response
    .json()
    .catch(() => ({ detail: `HTTP ${response.status}` }));
  if (!response.ok) {
    const detail = record(json).detail;
    throw new Error(
      str(
        typeof detail === "object" ? record(detail).message : detail,
        str(record(json).message, `Request failed (${response.status})`),
      ),
    );
  }
  return json as T;
}
export function useForge(campaignId: string, onSelect: (id: string) => void) {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [networkError, setNetworkError] = useState("");
  const [lastSync, setLastSync] = useState<Date | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  const statusRef = useRef("");
  const selectedRef = useRef(campaignId);
  selectedRef.current = campaignId;
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const refresh = useCallback(() => setRefreshKey((k) => k + 1), []);
  useEffect(() => {
    setLoading(true);
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    const poll = async () => {
      try {
        const boot = await request<Bootstrap>("/bootstrap", {
          signal: abort.signal,
        });
        if (stopped) return;
        setBootstrap(boot);
        let initial: Campaign | undefined;
        if (!selectedRef.current) {
          const candidates = boot.campaigns
            .filter(
              (c) =>
                c.status === "completed" &&
                c.stage === "report" &&
                ![
                  "challenge",
                  "registered_evaluation",
                  "post_final_reproduction",
                ].includes(str(c.config?.kind, "")),
            )
            .sort((a, b) => b.created_at.localeCompare(a.created_at));
          for (const candidate of candidates) {
            const detail = await request<Campaign>(
              `/campaigns/${encodeURIComponent(candidate.id)}`,
              { signal: abort.signal },
            );
            if (stopped) return;
            if (
              detail.registered_report &&
              detail.counterexample &&
              detail.curriculum &&
              detail.training
            ) {
              initial = detail;
              break;
            }
          }
        }
        const id =
          selectedRef.current ||
          initial?.id ||
          boot.campaigns.find(
            (c) => c.recorded && c.config?.kind !== "challenge",
          )?.id ||
          boot.selected_campaign_id ||
          boot.campaigns[0]?.id;
        if (id) {
          if (!selectedRef.current) selectRef.current(id);
          const detail =
            initial?.id === id
              ? initial
              : await request<Campaign>(
                  `/campaigns/${encodeURIComponent(id)}`,
                  { signal: abort.signal },
                );
          if (stopped) return;
          if (selectedRef.current && selectedRef.current !== id) return;
          setCampaign(detail);
          statusRef.current = detail.status;
        }
        setNetworkError("");
        setLastSync(new Date());
      } catch (error) {
        if (!stopped)
          setNetworkError(
            error instanceof Error ? error.message : "Connection lost",
          );
      } finally {
        if (!stopped) {
          setLoading(false);
          timer = setTimeout(
            poll,
            activeStatus(statusRef.current) ? 1000 : 3000,
          );
        }
      }
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
      abort.abort();
    };
  }, [campaignId, refreshKey]);
  const current = campaign?.id === campaignId || !campaignId ? campaign : null;
  return {
    bootstrap,
    campaign: current,
    networkError,
    lastSync,
    loading,
    refresh,
  };
}
const episodeCache = new Map<string, Episode>();
export function useEpisode(id?: string) {
  const [episode, setEpisode] = useState<Episode | null>(
    id ? episodeCache.get(id) || null : null,
  );
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    setEpisode(id ? episodeCache.get(id) || null : null);
    setError("");
    if (!id || episodeCache.has(id)) return;
    const abort = new AbortController();
    request<Episode>(
      id.startsWith("/api/incidents/")
        ? id.slice(4)
        : `/episodes/${encodeURIComponent(id)}`,
      {
        signal: abort.signal,
      },
    )
      .then((result) => {
        episodeCache.set(id, result);
        setEpisode(result);
      })
      .catch((err) => {
        if (!abort.signal.aborted) setError(err.message);
      });
    return () => abort.abort();
  }, [id, retry]);
  return { episode, error, retry: () => setRetry((v) => v + 1) };
}
export function actionKey(action: string) {
  return `forge-${action}-${crypto.randomUUID()}`;
}
export async function mutateCampaign(
  id: string,
  action: string,
  generation: number,
  key: string,
) {
  return request<Campaign>(`/campaigns/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": key },
    body: JSON.stringify({ expected_generation: generation }),
  });
}
