// 자동화가 커밋한 상태 JSON + GitHub run 정보를 화면 상태로 바꾸는 순수 규칙. React·fetch 없음.
// 설계 문서 3절(3.1~3.6)·2.5절 확정 문구의 유일한 구현처. `import type`만 허용(node --test가 타입 제거로 직접 실행).
import type { AutomationDef, TaskDef } from "./workspaces/types";

// ───────────────────────── 상태 파일 v2 (3.6절) ─────────────────────────

export type FileTaskStatus = "done" | "error" | "idle";

export type RealStatus = {
  id: string;
  name: string;
  dept: string;
  ok: boolean;
  running?: boolean;
  updated_at: string;
  summary: string;
  counts?: Record<string, number>;
  next_run?: string;
  log?: string[];
  link?: string;
  // v2 추가 필드 (구버전 파일은 전부 없음)
  run_id?: number | string;
  run_url?: string;
  request_id?: string;
  trigger?: "manual" | "schedule" | "local";
  started_at?: string;
  duration_sec?: number;
  tasks?: { id: string; status: FileTaskStatus; summary: string }[];
};

/** Worker `/api/status`가 주는 워크플로의 최신 유효 run (cancelled·skipped 제외) */
export type RunInfo = {
  id: number | string;
  status: "queued" | "in_progress" | "completed";
  conclusion: string | null;
  requestId?: string;
  startedAt?: string;
  completedAt?: string;
  url?: string;
};

/** 이 브라우저에서 방금 누른 요청 (sessionStorage, `/api/run`이 accepted일 때만 저장) */
export type LocalRequest = { requestId: string; at: string | number };

/** 상태 파일을 어디서 읽었는지 */
export type StatusSource = "github" | "static";

// ───────────────────────── 3.2 타입 ─────────────────────────

export type TaskState = "idle" | "running" | "done" | "error" | "planned";
export type RunPhase = "planned" | "idle" | "requested" | "queued" | "running" | "finishing" | "done" | "error";
export type WarnReason = "runner_waiting" | "schedule_missed";

export const LABELS: Record<TaskState, string> = {
  idle: "쉬는 중", running: "일하는 중", done: "끝남", error: "오류", planned: "준비 중",
};
export const STATE_CLASS: Record<TaskState, string> = {
  idle: "waiting", running: "working", done: "done", error: "error", planned: "planned",
};

export type AutomationView = {
  id: string; dept: string; name: string;
  phase: RunPhase;            // 내부 단계
  state: TaskState;           // 화면 pill (phase → 4어휘)
  sub: string;                // 부제 한 줄
  warn?: WarnReason;          // 노란 배너 사유 (규칙 3·10a)
  tasks: Record<string, { state: TaskState; note: string }>;
  lastRunAt?: string; nextRun?: string; runUrl?: string; link?: string;
  counts?: Record<string, number>; log?: string[];
};
export type DeptView = { state: TaskState | "none"; runningCount: number; automationIds: string[] };

export function phaseToState(phase: RunPhase): TaskState {
  switch (phase) {
    case "requested": case "queued": case "running": case "finishing": return "running";
    default: return phase;
  }
}

// ───────────────────────── 시간 상수 ─────────────────────────

/** 이 시간(시간 단위) 넘게 갱신이 없으면 "쉬는 중"으로 본다 (규칙 10a/10b) */
export const STALE_HOURS = 36;
/** 로컬 시작 요청이 유효한 시간 (규칙 2) */
export const LOCAL_REQUEST_TTL_MS = 3 * 60 * 1000;
/** queued 가 이만큼 넘으면 "실행기 기다리는 중" (규칙 3) */
export const RUNNER_WAIT_MS = 90 * 1000;
/** 성공 run 뒤 결과 파일을 기다리는 시간 (규칙 6의 T) */
export const RESULT_WAIT_MS: Record<StatusSource, number> = { github: 5 * 60 * 1000, static: 15 * 60 * 1000 };
/** 구버전 running:true 파일의 기본 예상 실행 시간(초) (규칙 7) */
export const LEGACY_DEFAULT_DURATION_SEC = 300;
/** 이보다 짧게 끝난 성공 run 은 "할 일 없이 끝난 확인 실행"(예약 확인·예약 수정)으로 보고 결과 파일을 요구하지 않는다 (규칙 6a, 2026-09-12) */
export const NOOP_RUN_MS = 90 * 1000;

// ───────────────────────── 2.5 확정 문구 ─────────────────────────

export const SUBTITLES = {
  planned: "준비 중",
  requested: "시작 요청됨",
  queued: "시작 준비 중",
  runnerWaiting: "실행기 기다리는 중",
  runningFor: (minutes: number) => `시작한 지 ${minutes}분째`,
  finishing: "결과 정리 중",
  logLink: "자세한 기록 보기",
  failedNoFile: "실행 실패 · 자세한 기록 보기",
  resultMissing: "결과가 올라오지 않았어요 · 자세한 기록 보기",
  legacyRunning: "실행 중",
  legacyLost: "결과를 못 받았어요",
  neverRan: "아직 실행한 적 없어요",
  lastRun: (ago: string) => `마지막 실행 ${ago}`,
  scheduleMissed: (ago: string) => `예약 실행이 안 되고 있어요 · 마지막 실행 ${ago}`,
} as const;

/** 배너 문구. 아이콘(🔴🟡⚪)은 level 로 화면이 붙인다 */
export const BANNERS = {
  failed: (name: string) => `${name}이(가) 실패했어요 · 자세한 기록 보기`,
  runnerWaiting: "실행기가 꺼져 있는 것 같아요 · 켜지면 자동으로 시작돼요",
  scheduleMissed: (ago: string) => `예약 실행이 밀리고 있어요 (마지막 실행 ${ago}) · 실행기가 켜져 있는지 확인해 주세요`,
  tokenExpiring: (days: number) => `실행 연결이 ${days}일 뒤 끊겨요 · 설정 안내 보기`,
  tokenBroken: "실행 연결이 끊겼어요 · 설정을 다시 해야 해요",
  tokenNoRepo: "실행 연결이 잘못됐어요 · 토큰이 ai-office 저장소를 못 봐요 (토큰의 Repository access 에 ai-office 를 넣어 주세요)",
  githubDown: "GitHub 응답이 없어요 · 잠시 뒤 자동으로 다시 확인해요",
  staleSource: (minutes: number) => `최신 상태를 못 가져왔어요 (${minutes}분 전 기준)`,
} as const;

export type BannerLevel = "error" | "warn" | "info";
export type Banner = { kind: WarnReason; level: BannerLevel; text: string; ids: string[] };

// ───────────────────────── 오늘 실행 이력 한 줄 표시 ─────────────────────────

export type HistoryLabel = { text: string; cls: string };

/** GitHub run 의 status/conclusion → 화면 문구·클래스 (취소는 회색) */
export function historyLabel(status: string, conclusion: string | null): HistoryLabel {
  if (status === "queued") return { text: "시작 준비 중", cls: STATE_CLASS.running };
  if (status !== "completed") return { text: LABELS.running, cls: STATE_CLASS.running };
  if (conclusion === "success") return { text: LABELS.done, cls: STATE_CLASS.done };
  if (conclusion === "cancelled" || conclusion === "skipped") return { text: "취소됨", cls: STATE_CLASS.planned };
  return { text: LABELS.error, cls: STATE_CLASS.error };
}

export const TRIGGER_LABEL = { manual: "수동", schedule: "예약", local: "이 PC", other: "기타" } as const;

/** 걸린 시간 문구: "45초" / "4.8분" / "14시간 18분" */
export function secondsText(sec: number): string {
  const s = Math.round(sec);
  if (s < 60) return `${s}초`;
  if (s < 3600) return `${(s / 60).toFixed(1)}분`;
  return `${Math.floor(s / 3600)}시간 ${Math.round((s % 3600) / 60)}분`;
}

/** 두 시각 사이 → secondsText. 값이 없으면 "" */
export function durationText(startedAt: string | null | undefined, completedAt: string | null | undefined): string {
  const a = toMs(startedAt);
  const b = toMs(completedAt);
  if (Number.isNaN(a) || Number.isNaN(b) || b < a) return "";
  return secondsText((b - a) / 1000);
}

// ───────────────────────── 시각 헬퍼 (순수, now 주입) ─────────────────────────

function toMs(v: string | number | undefined | null): number {
  if (v == null) return NaN;
  return typeof v === "number" ? v : Date.parse(v);
}

/** "방금 / N분 전 / N시간 전 / N일 전". 파싱 불가면 "" */
export function relativeTime(at: string | number | undefined | null, now: Date): string {
  const ms = now.getTime() - toMs(at);
  if (Number.isNaN(ms)) return "";
  const sec = Math.max(0, Math.floor(ms / 1000));
  if (sec < 60) return "방금";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}분 전`;
  const hours = Math.floor(min / 60);
  if (hours < 48) return `${hours}시간 전`;
  return `${Math.floor(hours / 24)}일 전`;
}

/** "시작한 지 N분째" (N ≥ 1). 시작 시각을 모르면 1분째 */
export function runningSince(startedAt: string | number | undefined | null, now: Date): string {
  const ms = now.getTime() - toMs(startedAt);
  const minutes = Number.isNaN(ms) ? 1 : Math.max(1, Math.floor(ms / 60000));
  return SUBTITLES.runningFor(minutes);
}

function ageMs(at: string | number | undefined | null, now: Date): number {
  const ms = now.getTime() - toMs(at);
  return Number.isNaN(ms) ? Number.POSITIVE_INFINITY : ms;
}

function isStale(file: RealStatus, now: Date): boolean {
  return ageMs(file.updated_at, now) > STALE_HOURS * 3600 * 1000;
}

function sameRun(file: RealStatus | null, run: RunInfo): boolean {
  return file != null && file.run_id != null && String(file.run_id) === String(run.id);
}

const FAILED_CONCLUSIONS = new Set(["failure", "timed_out", "startup_failure"]);

// ───────────────────────── 3.3 자동화 판정 ─────────────────────────

type Verdict = { phase: RunPhase; sub: string; warn?: WarnReason };

function judge(def: AutomationDef, file: RealStatus | null, run: RunInfo | null, local: LocalRequest | null, now: Date, source: StatusSource): Verdict {
  // 1. 워크플로 없음 → 준비 중
  if (!def.workflow) return { phase: "planned", sub: SUBTITLES.planned };

  // 2. 방금 누른 요청이 아직 run 으로 안 보임
  if (local && ageMs(local.at, now) < LOCAL_REQUEST_TTL_MS && (!run || run.requestId !== local.requestId)) {
    return { phase: "requested", sub: SUBTITLES.requested };
  }

  if (run) {
    // 3. 대기열
    if (run.status === "queued") {
      const waited = ageMs(run.startedAt, now);
      if (Number.isFinite(waited) && waited >= RUNNER_WAIT_MS) return { phase: "queued", sub: SUBTITLES.runnerWaiting, warn: "runner_waiting" };
      return { phase: "queued", sub: SUBTITLES.queued };
    }
    // 4. 실행 중
    if (run.status === "in_progress") return { phase: "running", sub: runningSince(run.startedAt, now) };

    if (run.status === "completed") {
      // 5. 실패
      if (run.conclusion != null && FAILED_CONCLUSIONS.has(run.conclusion)) {
        return { phase: "error", sub: sameRun(file, run) ? file!.summary : SUBTITLES.failedNoFile };
      }
      // 6. 성공했는데 파일이 이 run 것이 아님 (run_id 가 없는 구버전 파일은 updated_at ≥ startedAt 이면 같은 run 으로 본다)
      if (run.conclusion === "success") {
        const fileIsOlder = !file || (!sameRun(file, run) && toMs(file.updated_at) < toMs(run.startedAt));
        // 6a. 90초 안에 끝난 성공 run = 만들 것이 없어 바로 끝난 예약 확인(매시 정각)이나 예약 수정 — 결과 파일이 없는 게 정상이므로 파일 규칙(7~11)으로 넘어간다
        const took = run.completedAt ? toMs(run.completedAt) - toMs(run.startedAt) : NaN;
        const noop = Number.isFinite(took) && took >= 0 && took < NOOP_RUN_MS;
        if (fileIsOlder && !noop) {
          const elapsed = ageMs(run.completedAt ?? run.startedAt, now);
          if (elapsed < RESULT_WAIT_MS[source]) return { phase: "finishing", sub: SUBTITLES.finishing };
          return { phase: "error", sub: SUBTITLES.resultMissing };
        }
      }
    }
  }

  // 7. 구버전 파일 호환 (running:true) — 새 파이프라인은 running:true 를 쓰지 않는다
  if (file?.running === true) {
    const budget = 3 * (file.duration_sec ?? LEGACY_DEFAULT_DURATION_SEC) * 1000;
    if (ageMs(file.updated_at, now) < budget) return { phase: "running", sub: SUBTITLES.legacyRunning };
    return { phase: "error", sub: SUBTITLES.legacyLost };
  }

  // 8. 파일 없음
  if (!file) return { phase: "idle", sub: SUBTITLES.neverRan };

  // 9. 파일이 실패라고 함
  if (!file.ok) return { phase: "error", sub: file.summary };

  // 10a / 10b. 36시간 넘게 실행 없음
  if (isStale(file, now)) {
    const ago = relativeTime(file.updated_at, now) || `${STALE_HOURS}시간 전`;
    if (def.schedule) return { phase: "idle", sub: SUBTITLES.scheduleMissed(ago), warn: "schedule_missed" };
    return { phase: "idle", sub: SUBTITLES.lastRun(ago) };
  }

  // 11. 끝남
  return { phase: "done", sub: file.summary };
}

export function deriveAutomationView(
  def: AutomationDef,
  file: RealStatus | null,
  run: RunInfo | null,
  local: LocalRequest | null,
  now: Date,
  source: StatusSource = "github",
): AutomationView {
  const v = judge(def, file, run, local, now, source);
  const view: AutomationView = {
    id: def.id,
    dept: def.dept,
    name: def.name,
    phase: v.phase,
    state: phaseToState(v.phase),
    sub: v.sub,
    tasks: {},
  };
  if (v.warn) view.warn = v.warn;
  if (file?.updated_at) view.lastRunAt = file.updated_at;
  const nextRun = def.schedule ?? file?.next_run;
  if (nextRun) view.nextRun = nextRun;
  const runUrl = run?.url ?? file?.run_url;
  if (runUrl) view.runUrl = runUrl;
  if (file?.link) view.link = file.link;
  if (file?.counts) view.counts = file.counts;
  if (file?.log) view.log = file.log;
  view.tasks = deriveTaskStates(def, view, file);
  return view;
}

// ───────────────────────── 3.4 하위 작업(직원) 판정 ─────────────────────────

const ACTIVE_PHASES: ReadonlySet<RunPhase> = new Set(["requested", "queued", "running", "finishing"]);
const FILE_TASK_STATES: ReadonlySet<string> = new Set(["done", "error", "idle"]);

/**
 * planned → 전원 planned. 실행 중 단계 → planned 아닌 전원 running.
 * done/error/idle → 파일 tasks[] 의 status·summary 그대로, 파일에 없으면 자동화 상태 상속.
 * 파일 tasks 는 파일이 이번 결과일 때만 믿는다: done(규칙 11) 또는 error 이면서 파일 자체가 실패(규칙 5 같은 run·규칙 9).
 * idle(36시간 넘게 실행 없음)은 정의상 전원 쉬는 중.
 */
export function deriveTaskStates(def: AutomationDef, view: AutomationView, file: RealStatus | null): Record<string, { state: TaskState; note: string }> {
  const out: Record<string, { state: TaskState; note: string }> = {};
  const useFileTasks = file != null && (view.phase === "done" || (view.phase === "error" && !file.ok));
  const byId = new Map<string, { status: FileTaskStatus; summary: string }>();
  if (useFileTasks) for (const t of file!.tasks ?? []) byId.set(t.id, t);

  for (const task of def.tasks as TaskDef[]) {
    if (task.planned || view.phase === "planned") {
      out[task.id] = { state: "planned", note: SUBTITLES.planned };
      continue;
    }
    if (ACTIVE_PHASES.has(view.phase)) {
      out[task.id] = { state: "running", note: view.sub };
      continue;
    }
    const fromFile = byId.get(task.id);
    if (fromFile && FILE_TASK_STATES.has(fromFile.status)) {
      out[task.id] = { state: fromFile.status, note: fromFile.summary ?? "" };
      continue;
    }
    out[task.id] = { state: view.state, note: view.sub };
  }
  return out;
}

// ───────────────────────── 3.5 부서·집계 ─────────────────────────

const SEVERITY: Record<TaskState, number> = { error: 4, running: 3, done: 2, idle: 1, planned: 0 };

/** 부서의 자동화(workflow 있는 것)들의 최악값(error > running > done > idle). 0개면 "none" */
export function deriveDeptView(automationsOfDept: AutomationDef[], views: AutomationView[]): DeptView {
  const real = automationsOfDept.filter((a) => !!a.workflow);
  const automationIds = real.map((a) => a.id);
  if (real.length === 0) return { state: "none", runningCount: 0, automationIds };
  const byId = new Map(views.map((v) => [v.id, v] as const));
  let worst: TaskState = "idle";
  let runningCount = 0;
  for (const id of automationIds) {
    const v = byId.get(id);
    const s: TaskState = v ? v.state : "idle";
    if (s === "running") runningCount += 1;
    if (SEVERITY[s] > SEVERITY[worst]) worst = s;
  }
  return { state: worst, runningCount, automationIds };
}

export type TaskSummary = {
  counts: Record<Exclude<TaskState, "planned">, number>;
  automations: number;   // workflow 있는 자동화 수
  running: number;       // 그중 실행 중
  brief: string;         // "자동화 N개 중 M개 실행 중"
};

/** 요약 4칸: planned 아닌 직원 수를 상태별로. views 는 보이는 부서의 것만 넘긴다 */
export function summarizeTasks(views: AutomationView[], defs: AutomationDef[]): TaskSummary {
  const counts: TaskSummary["counts"] = { idle: 0, running: 0, done: 0, error: 0 };
  for (const v of views) {
    for (const t of Object.values(v.tasks)) {
      if (t.state === "planned") continue;
      counts[t.state] += 1;
    }
  }
  const realIds = new Set(defs.filter((d) => !!d.workflow).map((d) => d.id));
  const running = views.filter((v) => realIds.has(v.id) && v.state === "running").length;
  const automations = realIds.size;
  return { counts, automations, running, brief: `자동화 ${automations}개 중 ${running}개 실행 중` };
}

/** warn 이 하나라도 있으면 사유별로 배너 1줄. 예약 밀림은 가장 오래된 마지막 실행 기준 */
export function collectWarnings(views: AutomationView[], now: Date): Banner[] {
  const out: Banner[] = [];
  const waiting = views.filter((v) => v.warn === "runner_waiting");
  if (waiting.length) out.push({ kind: "runner_waiting", level: "warn", text: BANNERS.runnerWaiting, ids: waiting.map((v) => v.id) });
  const missed = views.filter((v) => v.warn === "schedule_missed");
  if (missed.length) {
    let oldest: string | undefined;
    for (const v of missed) {
      if (!v.lastRunAt) continue;
      if (oldest === undefined || toMs(v.lastRunAt) < toMs(oldest)) oldest = v.lastRunAt;
    }
    const ago = relativeTime(oldest, now) || `${STALE_HOURS}시간 전`;
    out.push({ kind: "schedule_missed", level: "warn", text: BANNERS.scheduleMissed(ago), ids: missed.map((v) => v.id) });
  }
  return out;
}

// ───────────────────────── 구버전 API (status.ts 가 아직 사용, 시그니처 유지) ─────────────────────────

export type RealDeptStatus = "완료" | "진행 중" | "오류" | "대기";

export function deriveDeptStatus(s: RealStatus, now: Date = new Date()): RealDeptStatus {
  if (s.running) return "진행 중";
  if (!s.ok) return "오류";
  const updated = Date.parse(s.updated_at);
  if (Number.isNaN(updated) || now.getTime() - updated > STALE_HOURS * 3600 * 1000) return "대기";
  return "완료";
}

export type Summary = {
  total: number;
  ok: number;
  error: number;
  running: number;
  stale: number;
  opsStatus: RealDeptStatus;
  brief: string;
};

export function summarize(all: RealStatus[], now: Date = new Date()): Summary {
  const statuses = all.map((s) => deriveDeptStatus(s, now));
  const count = (k: RealDeptStatus) => statuses.filter((x) => x === k).length;
  const total = all.length;
  const error = count("오류");
  const running = count("진행 중");
  const ok = count("완료");
  const stale = count("대기");
  let opsStatus: RealDeptStatus = "대기";
  if (total > 0) opsStatus = error ? "오류" : running ? "진행 중" : ok ? "완료" : "대기";
  const brief =
    total === 0
      ? "연결된 자동화 없음 — 상태 파일이 올라오면 여기에 표시됩니다."
      : `실제 ${total}개 팀 중 ${ok}개 정상, ${error}개 오류, ${running}개 실행 중, ${stale}개 오래됨`;
  return { total, ok, error, running, stale, opsStatus, brief };
}
