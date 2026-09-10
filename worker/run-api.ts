// /api/run · /api/status 순수 로직. vinext/next 를 import 하지 않고, 시간·GitHub·저장소는 deps 로 주입받는다.
import { DAILY_RUN_LIMIT, RUNS_PER_PAGE, STATUS_CACHE_MS, TOO_SOON_MS } from "./config.ts";
import { GitHubAuthError, GitHubNotFoundError, GitHubUnavailableError, type GitHubLike, type RunSummary } from "./github.ts";

// ── 사무실 설정(구조만 맞으면 됨 — app/workspaces 의 WorkspaceConfig 와 호환) ──
export type AutomationLike = { id: string; workflow?: string; inputs?: Record<string, string> };
export type WorkspaceLike = { id: string; automations: AutomationLike[] };

// ── decideRun ──
export type LatestRun = { status: string; conclusion: string | null } | null | undefined;
export type RunDecision = { kind: "accepted" } | { kind: "skipped"; reason: "already_running" | "too_soon" };

export function decideRun(latestRun: LatestRun, lastDispatchAt: number | undefined, now: number): RunDecision {
  if (latestRun && (latestRun.status === "queued" || latestRun.status === "in_progress")) {
    return { kind: "skipped", reason: "already_running" };
  }
  if (lastDispatchAt !== undefined && now - lastDispatchAt < TOO_SOON_MS) {
    return { kind: "skipped", reason: "too_soon" };
  }
  return { kind: "accepted" };
}

// ── 하루 상한 카운터 (사무실별, KST 날짜 키) ──
export type DailyCounterStore = { dateKey: string; counts: Record<string, number> };

export function createDailyCounterStore(): DailyCounterStore {
  return { dateKey: "", counts: {} };
}

/** KST(UTC+9) 기준 "YYYY-MM-DD" */
export function kstDateKey(nowMs: number): string {
  return new Date(nowMs + 9 * 60 * 60 * 1000).toISOString().slice(0, 10);
}

function rollDay(store: DailyCounterStore, nowMs: number): void {
  const key = kstDateKey(nowMs);
  if (store.dateKey !== key) {
    store.dateKey = key;
    store.counts = {};
  }
}

export function dailyCount(store: DailyCounterStore, ws: string, nowMs: number): number {
  rollDay(store, nowMs);
  return store.counts[ws] ?? 0;
}

export function addDailyCount(store: DailyCounterStore, ws: string, nowMs: number, n = 1): number {
  rollDay(store, nowMs);
  store.counts[ws] = (store.counts[ws] ?? 0) + n;
  return store.counts[ws];
}

// ── runs 가공 ──
/** display_title("수집 · req-2026…-a1b2")에서 requestId 추출. 없으면 null */
export function parseRequestId(displayTitle: string | null | undefined): string | null {
  const m = /req-[A-Za-z0-9-]+/.exec(displayTitle ?? "");
  return m ? m[0] : null;
}

function workflowFileOf(run: RunSummary): string {
  const path = run.path ?? "";
  const i = path.lastIndexOf("/");
  return i >= 0 ? path.slice(i + 1) : path;
}

/** cancelled/skipped 를 제외하고 워크플로 파일명별 최신(run id 최대) 1건 */
export function latestValidRunByWorkflow(runs: RunSummary[]): Map<string, RunSummary> {
  const out = new Map<string, RunSummary>();
  for (const run of runs) {
    if (run.conclusion === "cancelled" || run.conclusion === "skipped") continue;
    const file = workflowFileOf(run);
    if (!file) continue;
    const prev = out.get(file);
    if (!prev || run.id > prev.id) out.set(file, run);
  }
  return out;
}

export type RunView = {
  id: number;
  status: string;
  conclusion: string | null;
  requestId: string | null;
  startedAt: string | null;
  completedAt: string | null;
  url: string;
};

export function toRunView(run: RunSummary): RunView {
  return {
    id: run.id,
    status: run.status,
    conclusion: run.conclusion,
    requestId: parseRequestId(run.display_title),
    startedAt: run.run_started_at,
    completedAt: run.status === "completed" ? run.updated_at : null,
    url: run.html_url,
  };
}

// ── deps / env ──
export type GitHubErrorKind = null | "auth" | "not_found" | "unavailable";

function classifyGitHubError(error: unknown): GitHubErrorKind {
  if (error instanceof GitHubAuthError) return "auth";
  if (error instanceof GitHubNotFoundError) return "not_found";
  return "unavailable";
}

export type StatusBody = {
  checkedAt: string;
  /** githubError: null 정상 / auth 401·403 / not_found 저장소 접근 불가 / unavailable 5xx·네트워크 */
  config: { canRun: boolean; tokenExpiresAt: string | null; githubError: GitHubErrorKind };
  runs: Record<string, RunView | null>;
  files: Record<string, unknown | null>;
  source: "github" | "static";
};

export type RunApiEnv = {
  ASSETS: { fetch(request: Request): Promise<Response> };
  GITHUB_TOKEN?: string;
};

export type RunApiDeps = {
  /** epoch ms */
  now: () => number;
  workspaces: Record<string, WorkspaceLike>;
  /** 토큰이 없으면 null */
  github: GitHubLike | null;
  dailyCounter: DailyCounterStore;
  /** `${ws}/${automationId}` → 마지막 dispatch 시각(ms) */
  dispatchLog: Map<string, number>;
  /** ws → 캐시된 /api/status 응답 */
  statusCache: Map<string, { at: number; body: StatusBody }>;
};

export function createRunApiStores(): Pick<RunApiDeps, "dailyCounter" | "dispatchLog" | "statusCache"> {
  return { dailyCounter: createDailyCounterStore(), dispatchLog: new Map(), statusCache: new Map() };
}

const MAX_BODY_BYTES = 1024;
const REQUEST_ID_RE = /^req-[A-Za-z0-9-]{1,80}$/;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

/** Origin 이 있는데 호스트가 다르면 403, Sec-Fetch-Site: cross-site 면 403. 둘 다 없으면(curl) 통과 */
export function isCrossOrigin(request: Request): boolean {
  const origin = request.headers.get("Origin");
  if (origin) {
    let originHost: string;
    try {
      originHost = new URL(origin).host;
    } catch {
      return true;
    }
    if (originHost !== new URL(request.url).host) return true;
  }
  const site = request.headers.get("Sec-Fetch-Site");
  if (site && site.toLowerCase() === "cross-site") return true;
  return false;
}

function githubErrorResponse(error: unknown): Response | null {
  if (error instanceof GitHubAuthError) return json({ error: "github_auth" }, 502);
  if (error instanceof GitHubUnavailableError) return json({ error: "github_unavailable" }, 502);
  return null;
}

// ── POST /api/run ──
export type RunResult = { id: string; accepted: true; requestedAt: string } | { id: string; skipped: "already_running" | "too_soon" };

export async function handleRun(request: Request, env: RunApiEnv, deps: RunApiDeps): Promise<Response> {
  // 1. 메서드 · Content-Type · 본문 크기 · JSON
  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
  const contentType = request.headers.get("Content-Type") ?? "";
  if (!contentType.toLowerCase().includes("application/json")) return json({ error: "bad_request" }, 400);
  const declared = Number(request.headers.get("Content-Length") ?? "0");
  if (declared > MAX_BODY_BYTES) return json({ error: "bad_request" }, 400);
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > MAX_BODY_BYTES) return json({ error: "bad_request" }, 400);
  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return json({ error: "bad_request" }, 400);
  }
  if (!body || typeof body !== "object") return json({ error: "bad_request" }, 400);
  const { ws, automation, requestId } = body as Record<string, unknown>;
  if (typeof ws !== "string" || !ws || typeof automation !== "string" || !automation || typeof requestId !== "string" || !REQUEST_ID_RE.test(requestId)) {
    return json({ error: "bad_request" }, 400);
  }

  // 2. 출처
  if (isCrossOrigin(request)) return json({ error: "forbidden" }, 403);

  // 4. 허용 목록 (사무실 설정) — 워크플로 파일명·inputs 는 항상 설정값
  const workspace = deps.workspaces[ws];
  if (!workspace) return json({ error: "not_found" }, 404);
  let targets: AutomationLike[];
  if (automation === "all") {
    targets = workspace.automations.filter((a) => a.workflow);
    if (targets.length === 0) return json({ error: "not_found" }, 404);
  } else {
    const def = workspace.automations.find((a) => a.id === automation);
    if (!def || !def.workflow) return json({ error: "not_found" }, 404);
    targets = [def];
  }

  // GitHub 연결 (토큰 없음 = 실행 연결 없음)
  const github = deps.github;
  if (!github) return json({ error: "github_auth" }, 502);

  const now = deps.now();

  // 5. 자동화마다 decideRun
  let latest: Map<string, RunSummary>;
  try {
    latest = latestValidRunByWorkflow(await github.listRuns(RUNS_PER_PAGE));
  } catch (error) {
    const res = githubErrorResponse(error);
    if (res) return res;
    throw error;
  }
  const plan: Array<{ def: AutomationLike; decision: RunDecision }> = targets.map((def) => ({
    def,
    decision: decideRun(latest.get(def.workflow as string), deps.dispatchLog.get(`${ws}/${def.id}`), now),
  }));

  // 3. 하루 상한 — 이번에 accepted 될 개수를 더해 오늘(KST) 누계가 상한을 넘으면 429 (skipped 는 세지 않음)
  const acceptedCount = plan.filter((p) => p.decision.kind === "accepted").length;
  if (dailyCount(deps.dailyCounter, ws, now) + acceptedCount > DAILY_RUN_LIMIT) {
    return json({ error: "daily_limit" }, 429);
  }

  // dispatch (설정 순서대로, "all" 이면 같은 requestId 전파)
  const results: RunResult[] = [];
  const requestedAt = new Date(now).toISOString();
  for (const { def, decision } of plan) {
    if (decision.kind === "skipped") {
      results.push({ id: def.id, skipped: decision.reason });
      continue;
    }
    try {
      await github.dispatch(def.workflow as string, { ...(def.inputs ?? {}), request_id: requestId });
    } catch (error) {
      const res = githubErrorResponse(error);
      if (res) return res;
      throw error;
    }
    deps.dispatchLog.set(`${ws}/${def.id}`, now);
    addDailyCount(deps.dailyCounter, ws, now, 1);
    results.push({ id: def.id, accepted: true, requestedAt });
  }

  // 6. 200 results
  return json({ results });
}

// ── GET /api/status?ws=… ──
async function readStaticFile(env: RunApiEnv, origin: string, ws: string, id: string): Promise<unknown | null> {
  try {
    const res = await env.ASSETS.fetch(new Request(`${origin}/status/${encodeURIComponent(ws)}/${encodeURIComponent(id)}.json`));
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function buildStatus(ws: string, workspace: WorkspaceLike, origin: string, env: RunApiEnv, deps: RunApiDeps): Promise<StatusBody> {
  const now = deps.now();
  const github = deps.github;
  const automations = workspace.automations.filter((a) => a.workflow);
  const runs: Record<string, RunView | null> = {};
  const files: Record<string, unknown | null> = {};
  let source: StatusBody["source"] = github ? "github" : "static";
  let githubError: GitHubErrorKind = null;

  if (github) {
    try {
      const latest = latestValidRunByWorkflow(await github.listRuns(RUNS_PER_PAGE));
      for (const a of automations) {
        const run = latest.get(a.workflow as string);
        runs[a.id] = run ? toRunView(run) : null;
      }
    } catch (error) {
      source = "static";
      githubError = classifyGitHubError(error);
    }
  }

  for (const a of automations) {
    let file: unknown | null = null;
    let ok = false;
    if (github) {
      try {
        file = await github.readStatusFile(ws, a.id);
        // runs 조회가 실패했는데 파일도 없으면(404) 토큰이 저장소를 못 보는 것 → 정적 파일로
        ok = file != null || githubError === null;
      } catch {
        // Contents 만 실패(권한에 Contents:Read 없음 등)면 실행은 되므로 canRun 은 유지하고 정적 파일로 대신한다
        ok = false;
      }
    }
    if (!ok) {
      source = "static";
      file = await readStaticFile(env, origin, ws, a.id);
    }
    files[a.id] = file;
  }

  return {
    checkedAt: new Date(now).toISOString(),
    config: {
      // 토큰이 있어도 인증 실패·저장소 접근 불가면 시작 버튼을 숨긴다
      canRun: Boolean(github) && githubError !== "auth" && githubError !== "not_found",
      tokenExpiresAt: github?.tokenExpiresAt ?? null,
      githubError,
    },
    runs,
    files,
    source,
  };
}

export async function handleStatus(request: Request, env: RunApiEnv, deps: RunApiDeps): Promise<Response> {
  if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405);
  const url = new URL(request.url);
  const ws = url.searchParams.get("ws") ?? "";
  const workspace = deps.workspaces[ws];
  if (!workspace) return json({ error: "not_found" }, 404);

  const now = deps.now();
  const cached = deps.statusCache.get(ws);
  if (cached && now - cached.at < STATUS_CACHE_MS) return json(cached.body);

  const body = await buildStatus(ws, workspace, url.origin, env, deps);
  deps.statusCache.set(ws, { at: now, body });
  return json(body);
}
