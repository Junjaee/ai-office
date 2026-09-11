// /api/run · /api/status · /api/history · /api/review 순수 로직. vinext/next 를 import 하지 않고, 시간·GitHub·저장소는 deps 로 주입받는다.
import {
  DAILY_RUN_LIMIT, HISTORY_CACHE_MAX, HISTORY_GITHUB_DAYS, HISTORY_PAST_CACHE_MS, HISTORY_START, HISTORY_TODAY_CACHE_MS,
  RUNS_PER_PAGE, STATUS_CACHE_MS, TOO_SOON_MS,
} from "./config.ts";
import { shiftDate } from "../app/history-rules.ts";
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

/** 실행 이력 한 줄 (취소 포함). id 는 GitHub 실행 번호, 이 PC 실행은 "local:<자동화>:<시작 시각>" */
export type HistoryTrigger = "manual" | "schedule" | "local" | "other";
export type HistoryItem = {
  id: string;
  automationId: string;
  status: string;
  conclusion: string | null;
  trigger: HistoryTrigger;
  requestId: string | null;
  startedAt: string | null;
  completedAt: string | null;
  url: string | null;
  summary: string | null;
  /** 실제로 걸린 시간(일지). 실행기 대기 시간은 빠진다 */
  durationSec: number | null;
};

/** 일지 한 줄 (automations/common/history_log.py 가 쓴다) */
export type ArchiveLine = {
  run_id?: number;
  automation?: string;
  request_id?: string;
  trigger?: string;
  started_at?: string;
  duration_sec?: number;
  ok?: boolean;
  summary?: string;
  url?: string;
  recorded_at?: string;
};

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export function isValidDate(date: string): boolean {
  if (!DATE_RE.test(date)) return false;
  const t = Date.parse(`${date}T00:00:00Z`);
  return !Number.isNaN(t) && new Date(t).toISOString().slice(0, 10) === date;
}

/** KST 하루 → GitHub `created` 필터용 UTC 범위 */
export function kstDayRangeUtc(date: string): { from: string; to: string } {
  const start = Date.parse(`${date}T00:00:00+09:00`);
  const iso = (ms: number) => new Date(ms).toISOString().replace(".000Z", "Z");
  return { from: iso(start), to: iso(start + 86_400_000 - 1000) };
}

function toTrigger(event: string): HistoryTrigger {
  return event === "workflow_dispatch" ? "manual" : event === "schedule" ? "schedule" : "other";
}

/** GitHub run → 이력 한 줄. 이 사무실 자동화의 워크플로가 아니면 뺀다 */
export function historyFromRuns(runs: RunSummary[], automations: WorkspaceLike["automations"]): HistoryItem[] {
  const byFile = new Map<string, string>();
  for (const a of automations) if (a.workflow) byFile.set(a.workflow, a.id);
  const out: HistoryItem[] = [];
  for (const run of runs) {
    const automationId = byFile.get(workflowFileOf(run));
    if (!automationId) continue;
    out.push({
      id: String(run.id),
      automationId,
      status: run.status,
      conclusion: run.conclusion,
      trigger: toTrigger(run.event),
      requestId: parseRequestId(run.display_title),
      startedAt: run.run_started_at,
      completedAt: run.status === "completed" ? run.updated_at : null,
      url: run.html_url || null,
      summary: null,
      durationSec: null,
    });
  }
  return out;
}

/** 일지 파일(jsonl) → 줄 목록. 깨진 줄은 건너뛴다 */
export function parseArchive(text: string, automationId: string): ArchiveLine[] {
  const out: ArchiveLine[] = [];
  for (const raw of text.split("\n")) {
    const s = raw.trim();
    if (!s) continue;
    let line: ArchiveLine;
    try {
      line = JSON.parse(s) as ArchiveLine;
    } catch {
      continue;
    }
    if (!line || typeof line !== "object") continue;
    out.push({ ...line, automation: line.automation ?? automationId });
  }
  return out;
}

/** 일지 한 줄의 KST 날짜 (스크립트 시작 시각, 없으면 기록 시각) */
export function archiveDate(line: ArchiveLine): string | null {
  const when = line.started_at ?? line.recorded_at;
  const ms = when ? Date.parse(when) : NaN;
  return Number.isNaN(ms) ? null : kstDateKey(ms);
}

function archiveKey(line: ArchiveLine): string {
  return line.run_id != null ? String(line.run_id) : `local:${line.automation}:${line.started_at ?? line.recorded_at ?? ""}`;
}

function itemFromArchive(line: ArchiveLine): HistoryItem {
  const started = line.started_at ?? null;
  const startMs = started ? Date.parse(started) : NaN;
  const completedAt =
    !Number.isNaN(startMs) && typeof line.duration_sec === "number" ? new Date(startMs + line.duration_sec * 1000).toISOString() : (line.recorded_at ?? null);
  const trigger: HistoryTrigger = line.trigger === "manual" || line.trigger === "schedule" || line.trigger === "local" ? line.trigger : "other";
  return {
    id: archiveKey(line),
    automationId: line.automation ?? "",
    status: "completed",
    conclusion: line.ok === false ? "failure" : "success",
    trigger,
    requestId: line.request_id ?? null,
    startedAt: started,
    completedAt,
    url: line.url ?? null,
    summary: line.summary ?? null,
    durationSec: typeof line.duration_sec === "number" ? line.duration_sec : null,
  };
}

/**
 * GitHub 목록 + 일지 → 실행 번호로 합친다 (상태·시각·링크는 GitHub, 요약·걸린 시간은 일지). 최신순.
 * 실행이 속하는 날은 GitHub(요청해 만든 날)이 정한다 — 실행기가 꺼져 밤새 대기했다가 다음 날 돈 실행도 요청한 날에 한 번만 보인다.
 * githubAuthoritative 가 false(GitHub 실패·보관 기간 밖)면 그날 일지의 실행을 그대로 보여 준다.
 */
export function mergeHistory(fromGithub: HistoryItem[], lines: ArchiveLine[], date: string, githubAuthoritative: boolean): HistoryItem[] {
  const byId = new Map<string, HistoryItem>(fromGithub.map((h) => [h.id, { ...h }]));
  // 1) 날짜와 상관없이 같은 실행 번호의 요약·걸린 시간을 붙인다
  for (const line of lines) {
    if (line.run_id == null) continue;
    const hit = byId.get(String(line.run_id));
    if (!hit) continue;
    if (line.summary) hit.summary = line.summary;
    if (typeof line.duration_sec === "number") hit.durationSec = line.duration_sec;
  }
  // 2) 그날 일지에만 있는 실행: 이 PC 실행은 늘, GitHub 번호가 있는 실행은 GitHub 이 믿을 만하지 않을 때만
  for (const line of lines) {
    if (archiveDate(line) !== date) continue;
    const key = archiveKey(line);
    if (byId.has(key)) continue;
    if (line.run_id != null && githubAuthoritative) continue;
    byId.set(key, itemFromArchive(line));
  }
  const at = (h: HistoryItem) => (h.startedAt ? Date.parse(h.startedAt) : 0) || 0;
  return [...byId.values()].sort((a, b) => at(b) - at(a) || b.id.localeCompare(a.id, undefined, { numeric: true }));
}

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

/** GET /api/history 응답 */
export type HistoryBody = {
  date: string;
  today: string;
  start: string;
  items: HistoryItem[];
  /** github: GitHub 목록 + 일지 / archive: GitHub 실패, 일지만 / static: 토큰 없음 */
  source: "github" | "archive" | "static";
  partial: boolean;
  checkedAt: string;
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
  /** "<ws>/<date>" → 캐시된 /api/history 응답 */
  historyCache: Map<string, { at: number; body: HistoryBody }>;
  /** "review/<ws>/<automation>" → 캐시된 /api/review 응답 */
  reviewCache: Map<string, { at: number; body: ReviewBody }>;
};

export function createRunApiStores(): Pick<RunApiDeps, "dailyCounter" | "dispatchLog" | "statusCache" | "historyCache" | "reviewCache"> {
  return { dailyCounter: createDailyCounterStore(), dispatchLog: new Map(), statusCache: new Map(), historyCache: new Map(), reviewCache: new Map() };
}

const MAX_BODY_BYTES = 2048;
const REQUEST_ID_RE = /^req-[A-Za-z0-9-]{1,80}$/;
/** 화면이 덧붙일 수 있는 workflow 입력값 — 이름·형식 허용 목록 (그 밖의 키는 400) */
const RUN_INPUT_RULES: Record<string, RegExp> = {
  mode: /^(topics|queue|publish|edit)$/,
  picks: /^[a-f0-9]{8}(,[a-f0-9]{8}){0,19}$/,
  // 예약 수정: id=cancel | id=HH:MM | id=YYYY-MM-DDTHH:MM (쉼표로 여러 개)
  edits: /^[a-f0-9]{8}=(cancel|\d{2}:\d{2}|\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(,[a-f0-9]{8}=(cancel|\d{2}:\d{2}|\d{4}-\d{2}-\d{2}T\d{2}:\d{2})){0,19}$/,
};

/** 요청 본문의 inputs → 검증된 문자열 맵. 없으면 {}. 허용되지 않은 키·형식이면 null */
export function parseRunInputs(raw: unknown): Record<string, string> | null {
  if (raw === undefined || raw === null) return {};
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(raw as Record<string, unknown>)) {
    const rule = RUN_INPUT_RULES[k];
    if (!rule || typeof v !== "string" || !rule.test(v)) return null;
    out[k] = v;
  }
  return out;
}

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
  const { ws, automation, requestId, inputs: rawInputs } = body as Record<string, unknown>;
  if (typeof ws !== "string" || !ws || typeof automation !== "string" || !automation || typeof requestId !== "string" || !REQUEST_ID_RE.test(requestId)) {
    return json({ error: "bad_request" }, 400);
  }
  const extraInputs = parseRunInputs(rawInputs);
  if (extraInputs === null) return json({ error: "bad_request" }, 400);
  // 화면 입력값(mode·picks)은 자동화 하나를 지정할 때만 — "all" 에는 붙이지 않는다
  if (automation === "all" && Object.keys(extraInputs).length > 0) return json({ error: "bad_request" }, 400);

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
  // 예약 수정(mode=edit)은 검토 파일만 고치는 20초짜리 실행이라 "실행 중"·"너무 빠름" 보호를 건너뛴다 (워크플로 concurrency 가 순서를 지킨다)
  const isEdit = extraInputs.mode === "edit";
  const plan: Array<{ def: AutomationLike; decision: RunDecision }> = targets.map((def) => ({
    def,
    decision: isEdit ? { kind: "accepted" } : decideRun(latest.get(def.workflow as string), deps.dispatchLog.get(`${ws}/${def.id}`), now),
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
      await github.dispatch(def.workflow as string, { ...(def.inputs ?? {}), ...extraInputs, request_id: requestId });
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
      const allRuns = await github.listRuns(RUNS_PER_PAGE);
      const latest = latestValidRunByWorkflow(allRuns);
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

// ── GET /api/review?ws=…&automation=… ── 주제 검토 파일(public/review/<ws>/<automation>.json)
export type ReviewBody = {
  ws: string;
  automation: string;
  /** 파일 내용 그대로 (없으면 null) */
  file: unknown | null;
  source: "github" | "static";
  checkedAt: string;
};

const AUTOMATION_ID_RE = /^[a-z0-9_]{1,40}$/;

async function readStaticReview(env: RunApiEnv, origin: string, ws: string, id: string): Promise<unknown | null> {
  try {
    const res = await env.ASSETS.fetch(new Request(`${origin}/review/${encodeURIComponent(ws)}/${encodeURIComponent(id)}.json`));
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function handleReview(request: Request, env: RunApiEnv, deps: RunApiDeps): Promise<Response> {
  if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405);
  const url = new URL(request.url);
  const ws = url.searchParams.get("ws") ?? "";
  const automation = url.searchParams.get("automation") ?? "";
  const workspace = deps.workspaces[ws];
  if (!workspace || !AUTOMATION_ID_RE.test(automation)) return json({ error: "not_found" }, 404);
  if (!workspace.automations.some((a) => a.id === automation)) return json({ error: "not_found" }, 404);

  const now = deps.now();
  const key = `review/${ws}/${automation}`;
  const cached = deps.reviewCache.get(key);
  if (cached && now - cached.at < STATUS_CACHE_MS) return json(cached.body);

  let file: unknown | null = null;
  let source: ReviewBody["source"] = "static";
  if (deps.github) {
    try {
      const text = await deps.github.readRepoText(`public/review/${ws}/${automation}.json`);
      file = text ? JSON.parse(text) : null;
      source = "github";
    } catch {
      file = null;
    }
  }
  if (source !== "github") file = await readStaticReview(env, url.origin, ws, automation);
  const body: ReviewBody = { ws, automation, file, source, checkedAt: new Date(now).toISOString() };
  deps.reviewCache.set(key, { at: now, body });
  return json(body);
}

// ── GET /api/history?ws=…&date=YYYY-MM-DD ──
export async function buildHistory(ws: string, workspace: WorkspaceLike, date: string, deps: RunApiDeps): Promise<HistoryBody> {
  const now = deps.now();
  const base = { date, today: kstDateKey(now), start: HISTORY_START, checkedAt: new Date(now).toISOString() };
  const github = deps.github;
  if (!github) return { ...base, items: [], source: "static", partial: false };
  if (date < HISTORY_START) return { ...base, items: [], source: "github", partial: false };

  let fromGithub: HistoryItem[] = [];
  let githubFailed = false;
  try {
    const { from, to } = kstDayRangeUtc(date);
    fromGithub = historyFromRuns(await github.listRunsBetween(from, to), workspace.automations);
  } catch {
    githubFailed = true;
  }
  // 그 달 일지 + 일주일 뒤가 다음 달이면 그 달 일지도 (요청한 날 뒤에 돈 실행의 요약을 찾으려고)
  let archiveFailed = false;
  const months = [...new Set([date.slice(0, 7), shiftDate(date, 7).slice(0, 7)])];
  const files = workspace.automations
    .filter((a) => a.workflow)
    .flatMap((a) => months.map((m) => ({ id: a.id, path: `history/${ws}/${a.id}/${m}.jsonl` })));
  const lines = (
    await Promise.all(
      files.map(async (f) => {
        try {
          const text = await github.readRepoText(f.path);
          return text ? parseArchive(text, f.id) : [];
        } catch {
          archiveFailed = true;
          return [];
        }
      }),
    )
  ).flat();
  const authoritative = !githubFailed && date >= shiftDate(base.today, -(HISTORY_GITHUB_DAYS - 1));
  return {
    ...base,
    items: mergeHistory(fromGithub, lines, date, authoritative),
    source: githubFailed ? "archive" : "github",
    partial: githubFailed || archiveFailed,
  };
}

export async function handleHistory(request: Request, deps: RunApiDeps): Promise<Response> {
  if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405);
  const url = new URL(request.url);
  const ws = url.searchParams.get("ws") ?? "";
  const date = url.searchParams.get("date") ?? "";
  const workspace = deps.workspaces[ws];
  if (!workspace) return json({ error: "not_found" }, 404);
  const now = deps.now();
  const today = kstDateKey(now);
  if (!isValidDate(date) || date > today) return json({ error: "bad_request" }, 400);

  const key = `${ws}/${date}`;
  const ttl = date === today ? HISTORY_TODAY_CACHE_MS : HISTORY_PAST_CACHE_MS;
  const cached = deps.historyCache.get(key);
  if (cached && now - cached.at < ttl) return json(cached.body);

  const body = await buildHistory(ws, workspace, date, deps);
  deps.historyCache.delete(key);
  deps.historyCache.set(key, { at: now, body });
  while (deps.historyCache.size > HISTORY_CACHE_MAX) deps.historyCache.delete(deps.historyCache.keys().next().value as string);
  return json(body);
}
