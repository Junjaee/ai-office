"use client";
// 실제 상태 조회: /api/status(10초/60초 폴링) + 정적 파일 폴백 + 이 브라우저의 "시작 요청됨" → 3절 규칙으로 판정.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BANNERS,
  LOCAL_REQUEST_TTL_MS,
  collectWarnings,
  deriveAutomationView,
  deriveDeptView,
  summarizeTasks,
  type AutomationView,
  type DeptView,
  type LocalRequest,
  type RealStatus,
  type RunInfo,
  type StatusSource,
  type TaskSummary,
} from "./status-rules";
import type { AutomationDef, WorkspaceConfig } from "./workspaces/types";

/** Worker `/api/status` 응답 (worker/run-api.ts StatusBody 와 같은 모양) */
export type ApiStatus = {
  checkedAt: string;
  config: { canRun: boolean; tokenExpiresAt?: string | null; githubError?: null | "auth" | "not_found" | "unavailable" };
  runs: Record<string, RunInfo | null>;
  files: Record<string, RealStatus | null>;
  source: StatusSource;
};

export type UiBanner = { key: string; level: "error" | "warn" | "info"; text: string; href?: string };

export type LiveState = {
  views: AutomationView[];
  deptViews: Record<string, DeptView>;
  summary: TaskSummary;
  banners: UiBanner[];
  hotRoom: string | null;
  source: StatusSource | null;
  checkedAt: Date | null;
  canRun: boolean | null;
  loaded: boolean;
};

const FAST_MS = 10_000;
const SLOW_MS = 60_000;
const ACTIVE = new Set(["requested", "queued", "running", "finishing"]);

// ───────── 이 브라우저의 "시작 요청됨" (sessionStorage, accepted 일 때만) ─────────

function storageKey(ws: string) {
  return `ai-office.requests.${ws}`;
}

export function readLocalRequests(ws: string): Record<string, LocalRequest> {
  try {
    const raw = sessionStorage.getItem(storageKey(ws));
    if (!raw) return {};
    const data = JSON.parse(raw) as Record<string, LocalRequest>;
    const now = Date.now();
    const out: Record<string, LocalRequest> = {};
    for (const [id, req] of Object.entries(data)) {
      const at = typeof req.at === "number" ? req.at : Date.parse(req.at);
      if (now - at < LOCAL_REQUEST_TTL_MS) out[id] = req;
    }
    return out;
  } catch {
    return {};
  }
}

export function writeLocalRequest(ws: string, id: string, requestId: string) {
  try {
    const all = readLocalRequests(ws);
    all[id] = { requestId, at: Date.now() };
    sessionStorage.setItem(storageKey(ws), JSON.stringify(all));
  } catch {
    /* 저장 불가 환경이면 무시 */
  }
}

/** run 목록에 같은 requestId 가 나타나면 로컬 요청은 역할이 끝난 것 */
function clearMatchedRequests(ws: string, runs: Record<string, RunInfo | null>) {
  try {
    const all = readLocalRequests(ws);
    let changed = false;
    for (const [id, req] of Object.entries(all)) {
      if (runs[id]?.requestId === req.requestId) {
        delete all[id];
        changed = true;
      }
    }
    if (changed) sessionStorage.setItem(storageKey(ws), JSON.stringify(all));
  } catch {
    /* ignore */
  }
}

// ───────── 조회 ─────────

async function fetchApiStatus(ws: string): Promise<ApiStatus> {
  const r = await fetch(`/api/status?ws=${encodeURIComponent(ws)}&t=${Date.now()}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return (await r.json()) as ApiStatus;
}

/** Worker 가 응답하지 않을 때: 배포된 정적 파일만 읽는다 (run 정보 없음, 시작 불가) */
async function fetchStaticStatus(ws: string, defs: AutomationDef[]): Promise<ApiStatus> {
  const bust = `?t=${Date.now()}`;
  const files: Record<string, RealStatus | null> = {};
  await Promise.all(
    defs
      .filter((d) => d.workflow)
      .map(async (d) => {
        try {
          const r = await fetch(`/status/${ws}/${d.id}.json${bust}`, { cache: "no-store" });
          files[d.id] = r.ok ? ((await r.json()) as RealStatus) : null;
        } catch {
          files[d.id] = null;
        }
      }),
  );
  return { checkedAt: new Date().toISOString(), config: { canRun: false }, runs: {}, files, source: "static" };
}

/** 개발용 상태 주입: ?mock=done|running|queued|runner_waiting|finishing|error|idle|schedule_missed|static|no_token|empty */
function mockStatus(mode: string, defs: AutomationDef[]): ApiStatus {
  const now = Date.now();
  const iso = (ms: number) => new Date(now + ms).toISOString();
  const runs: Record<string, RunInfo | null> = {};
  const files: Record<string, RealStatus | null> = {};
  let source: StatusSource = "github";
  defs
    .filter((d) => d.workflow)
    .forEach((d, i) => {
      const runId = 1000 + i;
      const url = `https://github.com/Junjaee/ai-office/actions/runs/${runId}`;
      const okFile = (over: Partial<RealStatus> = {}): RealStatus => ({
        id: d.id,
        name: d.name,
        dept: d.dept,
        ok: true,
        running: false,
        updated_at: iso(-20 * 60000),
        summary: "신규 3건, 확정본 교체 1건, 실패 0건, 1.9분",
        counts: { new: 3, replaced: 1, failed: 0, total: 5898 },
        next_run: d.schedule ?? "",
        log: ["신규 3건, 확정본 교체 1건", "[신규] 제22대/과학기술정보방송통신위원회/….pdf"],
        link: "https://drive.google.com/",
        run_id: runId,
        run_url: url,
        trigger: "manual",
        started_at: iso(-22 * 60000),
        duration_sec: 112,
        tasks: d.tasks.filter((t) => !t.planned).map((t, j) => ({ id: t.id, status: "done", summary: j === 0 ? "신규 3건" : "교체 1건" })),
        ...over,
      });
      const run = (over: Partial<RunInfo>): RunInfo => ({
        id: runId,
        status: "completed",
        conclusion: "success",
        startedAt: iso(-22 * 60000),
        completedAt: iso(-20 * 60000),
        url,
        ...over,
      });
      switch (mode) {
        case "running":
          runs[d.id] = run({ status: "in_progress", conclusion: null, startedAt: iso(-3 * 60000), completedAt: "" });
          files[d.id] = okFile({ run_id: runId - 1 });
          break;
        case "queued":
          runs[d.id] = run({ status: "queued", conclusion: null, startedAt: iso(-30000), completedAt: "" });
          files[d.id] = okFile({ run_id: runId - 1 });
          break;
        case "runner_waiting":
          runs[d.id] = run({ status: "queued", conclusion: null, startedAt: iso(-5 * 60000), completedAt: "" });
          files[d.id] = okFile({ run_id: runId - 1 });
          break;
        case "finishing":
          runs[d.id] = run({ startedAt: iso(-3 * 60000), completedAt: iso(-60000) });
          files[d.id] = okFile({ run_id: runId - 1, updated_at: iso(-2 * 3600000) });
          break;
        case "error":
          runs[d.id] = run({ conclusion: "failure" });
          files[d.id] = okFile({ ok: false, summary: "국회 사이트에 연결할 수 없어요", tasks: [{ id: d.tasks[0].id, status: "error", summary: "연결 실패" }] });
          break;
        case "idle":
          runs[d.id] = null;
          files[d.id] = null;
          break;
        case "schedule_missed":
          runs[d.id] = run({ startedAt: iso(-40 * 3600000), completedAt: iso(-40 * 3600000 + 120000) });
          files[d.id] = okFile({ updated_at: iso(-40 * 3600000) });
          break;
        case "static":
          source = "static";
          files[d.id] = okFile();
          break;
        case "empty":
          break;
        default:
          runs[d.id] = run({});
          files[d.id] = okFile();
      }
    });
  return { checkedAt: new Date().toISOString(), config: { canRun: mode !== "no_token" && mode !== "empty" }, runs, files, source };
}

// ───────── 판정 (순수) ─────────

export function buildLiveState(ws: WorkspaceConfig, api: ApiStatus | null, local: Record<string, LocalRequest>, now: Date): LiveState {
  const source: StatusSource | null = api ? api.source : null;
  const views = ws.automations.map((def) =>
    deriveAutomationView(def, api?.files[def.id] ?? null, api?.runs[def.id] ?? null, local[def.id] ?? null, now, source ?? "static"),
  );
  const deptViews: Record<string, DeptView> = {};
  for (const dept of ws.departments) {
    deptViews[dept.id] = deriveDeptView(ws.automations.filter((a) => a.dept === dept.id), views);
  }
  const shownDefs = ws.automations.filter((a) => !ws.hidden.includes(a.dept) && (ws.showPlanned || deptViews[a.dept]?.state !== "none"));
  const shownIds = new Set(shownDefs.map((a) => a.id));
  const visibleViews = views.filter((v) => shownIds.has(v.id));
  const summary = summarizeTasks(visibleViews, shownDefs);
  const hotRoom = visibleViews.find((v) => v.state === "running")?.dept ?? null;

  const banners: UiBanner[] = [];
  for (const v of visibleViews) {
    if (v.state === "error") banners.push({ key: `failed:${v.id}`, level: "error", text: BANNERS.failed(v.name), href: v.runUrl });
  }
  for (const b of collectWarnings(visibleViews, now)) banners.push({ key: b.kind, level: b.level, text: b.text });
  const ghErr = api?.config.githubError ?? null;
  if (ghErr === "not_found") {
    banners.push({ key: "token", level: "error", text: BANNERS.tokenNoRepo });
  } else if (ghErr === "auth" || (api && !api.config.canRun && api.source === "github")) {
    banners.push({ key: "token", level: "error", text: BANNERS.tokenBroken });
  } else if (ghErr === "unavailable") {
    banners.push({ key: "github-down", level: "warn", text: BANNERS.githubDown });
  } else if (api?.config.tokenExpiresAt) {
    const days = Math.floor((Date.parse(api.config.tokenExpiresAt) - now.getTime()) / 86400000);
    if (Number.isFinite(days) && days <= 30) {
      banners.push({ key: "token-expiring", level: days < 0 ? "error" : "warn", text: days < 0 ? BANNERS.tokenBroken : BANNERS.tokenExpiring(days) });
    }
  }
  if (api && api.source === "static" && shownDefs.some((a) => a.workflow)) {
    const newest = Object.values(api.files).reduce<number>((m, f) => (f?.updated_at ? Math.max(m, Date.parse(f.updated_at)) : m), 0);
    const minutes = newest ? Math.max(0, Math.floor((now.getTime() - newest) / 60000)) : 0;
    banners.push({ key: "stale", level: "info", text: BANNERS.staleSource(minutes) });
  }

  return {
    views,
    deptViews,
    summary,
    banners,
    hotRoom,
    source,
    checkedAt: api ? new Date(api.checkedAt) : null,
    canRun: api ? api.config.canRun : null,
    loaded: api !== null,
  };
}

// ───────── 훅 ─────────

export type LiveStatus = LiveState & { refresh: () => void; markRequested: (id: string, requestId: string) => void };

export function useLiveStatus(ws: WorkspaceConfig): LiveStatus {
  const [api, setApi] = useState<ApiStatus | null>(null);
  const [tick, setTick] = useState(0);
  const mock = useMemo(() => (typeof window !== "undefined" ? new URLSearchParams(window.location.search).get("mock") : null), []);

  const load = useCallback(async () => {
    if (mock) {
      setApi(mockStatus(mock, ws.automations));
      return;
    }
    try {
      const data = await fetchApiStatus(ws.id);
      clearMatchedRequests(ws.id, data.runs);
      setApi(data);
    } catch {
      try {
        setApi(await fetchStaticStatus(ws.id, ws.automations));
      } catch {
        /* 다음 폴링 때 재시도 */
      }
    }
  }, [ws, mock]);

  // tick 은 로컬 요청 저장·폴링 후 재판정을 강제하기 위한 값
  const state = useMemo(
    () => buildLiveState(ws, api, typeof window === "undefined" ? {} : readLocalRequests(ws.id), new Date()),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [ws, api, tick],
  );
  const activeRef = useRef(false);
  activeRef.current = state.views.some((v) => ACTIVE.has(v.phase));

  useEffect(() => {
    let alive = true;
    let timer = 0;
    const loop = async () => {
      await load();
      if (!alive) return;
      setTick((n) => n + 1);
      timer = window.setTimeout(loop, activeRef.current ? FAST_MS : SLOW_MS);
    };
    loop();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [load]);

  const refresh = useCallback(() => {
    load().then(() => setTick((n) => n + 1));
  }, [load]);

  const markRequested = useCallback(
    (id: string, requestId: string) => {
      writeLocalRequest(ws.id, id, requestId);
      setTick((n) => n + 1);
    },
    [ws.id],
  );

  return { ...state, refresh, markRequested };
}
