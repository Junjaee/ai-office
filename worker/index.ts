/** Cloudflare Worker 진입점 — /api/run · /api/status · /api/history · /api/review 만 직접 처리하고 나머지는 vinext 에 넘긴다. */
import { handleImageOptimization, DEFAULT_DEVICE_SIZES, DEFAULT_IMAGE_SIZES } from "vinext/server/image-optimization";
import handler from "vinext/server/app-router-entry";
import { WORKSPACES } from "../app/workspaces/index";
import { GitHubClient } from "./github.ts";
import { createRunApiStores, handleHistory, handleReview, handleRun, handleStatus, type RunApiDeps } from "./run-api.ts";
import { LEDGER_WATCH_JOB, MAIL_JOB, SCHEDULES, cronRequestId, dueJobs } from "./schedule.ts";
import {
  LEDGER_COOLDOWN_MS, LEDGER_WATCH_QUERY, MAIL_COOLDOWN_MS, MAIL_WATCH_QUERY,
  accessToken, coolEnough, googleCreds, newMailCount, shouldWake,
} from "./gmail.ts";

interface Env {
  ASSETS: Fetcher;
  /** fine-grained PAT (Cloudflare Secret / .dev.vars). 값은 절대 응답·로그에 내보내지 않는다 */
  GITHUB_TOKEN?: string;
  /** 공용 구글 토큰 — 1분마다 지메일에 새 상임위 메일이 있는지만 확인한다 (worker/gmail.ts) */
  GOOGLE_CLIENT_ID?: string;
  GOOGLE_CLIENT_SECRET?: string;
  GOOGLE_REFRESH_TOKEN?: string;
  IMAGES?: {
    input(stream: ReadableStream): {
      transform(options: Record<string, unknown>): {
        output(options: { format: string; quality: number }): Promise<{ response(): Response }>;
      };
    };
  };
}

// 인스턴스(isolate) 메모리 — 하루 상한 카운터 · 최근 dispatch 시각 · /api/status 15초 캐시
const stores = createRunApiStores();

function depsFor(env: Env): RunApiDeps {
  return {
    ...stores,
    now: () => Date.now(),
    workspaces: WORKSPACES,
    github: env.GITHUB_TOKEN ? new GitHubClient(env.GITHUB_TOKEN) : null,
  };
}

/** 마지막으로 깨운 시각 — 실행이 도는 동안 또 깨우지 않는다(같은 isolate 안에서만 기억) */
let lastMailDispatchMs: number | null = null;
let lastLedgerDispatchMs: number | null = null;

/** 검색어에 맞는 미처리 메일 수. 토큰이 없거나 실패하면 0(예약 처리는 그대로 진행한다). */
async function unreadCount(env: Env, query: string, nowMs: number): Promise<number> {
  const creds = googleCreds(env as unknown as Record<string, unknown>);
  if (!creds) return 0;
  try {
    const token = await accessToken(creds, fetch, nowMs);
    return await newMailCount(token, fetch, query);
  } catch (err) {
    console.error(`메일 확인 실패 — ${err instanceof Error ? err.message : String(err)}`);
    return 0;
  }
}

const worker = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/api/run") {
      return handleRun(request, env, depsFor(env));
    }

    if (url.pathname === "/api/status") {
      return handleStatus(request, env, depsFor(env));
    }

    if (url.pathname === "/api/history") {
      return handleHistory(request, depsFor(env));
    }

    if (url.pathname === "/api/review") {
      return handleReview(request, env, depsFor(env));
    }

    if (url.pathname === "/_vinext/image") {
      const allowedWidths = [...DEFAULT_DEVICE_SIZES, ...DEFAULT_IMAGE_SIZES];
      return handleImageOptimization(request, {
        fetchAsset: (path) => env.ASSETS.fetch(new Request(new URL(path, request.url))),
        transformImage: async (body, { width, format, quality }) => {
          if (!env.IMAGES) throw new Error("IMAGES binding is not configured");
          const result = await env.IMAGES.input(body).transform(width > 0 ? { width } : {}).output({ format, quality });
          return result.response();
        },
      }, allowedWidths);
    }

    return handler.fetch(request, env, ctx);
  },

  /** 1분마다 깨어나 "지금 돌 차례"인 자동화를 GitHub 에 요청한다.
   *
   * GitHub 의 예약(cron)은 부하가 높으면 지연되거나 버려져서(공식 문서, 실측 5분 예약이 4시간에 1번)
   * 시계를 이쪽으로 옮겼다 — 예약표는 worker/schedule.ts (사용자 결정 2026-09-17).
   * 하루 실행 상한(/api/run)은 사람이 누르는 버튼용이라 여기서는 적용하지 않는다.
   */
  async scheduled(controller: ScheduledController, env: Env, _ctx: ExecutionContext): Promise<void> {
    if (!env.GITHUB_TOKEN) {
      console.error("예약: GITHUB_TOKEN 이 없어 건너뜀");
      return;
    }
    const now = new Date(controller.scheduledTime);
    const jobs = dueJobs(SCHEDULES, now);

    const nowMs = now.getTime();
    // 상임위 메일·카드 문자는 시각이 아니라 "새 메일이 왔을 때" 돈다 — 매분 지메일만 가볍게 확인한다
    // (쉬는 시간 안이면 지메일을 아예 부르지 않는다)
    if (coolEnough(lastMailDispatchMs, nowMs, MAIL_COOLDOWN_MS)
        && shouldWake(await unreadCount(env, MAIL_WATCH_QUERY, nowMs), lastMailDispatchMs, nowMs, MAIL_COOLDOWN_MS)) {
      jobs.push(MAIL_JOB);
    }
    // 6시간 예약과 같은 분이면 예약 쪽 하나만 깨운다
    if (!jobs.some((j) => j.workflow === LEDGER_WATCH_JOB.workflow)
        && coolEnough(lastLedgerDispatchMs, nowMs, LEDGER_COOLDOWN_MS)
        && shouldWake(await unreadCount(env, LEDGER_WATCH_QUERY, nowMs), lastLedgerDispatchMs, nowMs, LEDGER_COOLDOWN_MS)) {
      jobs.push(LEDGER_WATCH_JOB);
    }

    if (jobs.length === 0) return;

    const github = new GitHubClient(env.GITHUB_TOKEN);
    const requestId = cronRequestId(now);
    for (const job of jobs) {
      try {
        await github.dispatch(job.workflow, { request_id: requestId, ...(job.inputs ?? {}) });
        if (job.workflow === MAIL_JOB.workflow) lastMailDispatchMs = now.getTime();
        // 6시간 예약으로 깨웠을 때도 기록 — 그 뒤 10분은 감시가 쉰다
        if (job.workflow === LEDGER_WATCH_JOB.workflow) lastLedgerDispatchMs = now.getTime();
        console.log(`예약 실행 요청: ${job.workflow} (${job.note}) ${requestId}`);
      } catch (err) {
        // 하나가 실패해도 나머지는 계속한다. 다음 분에 다시 기회가 온다
        console.error(`예약 실행 실패: ${job.workflow} — ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  },
};

export default worker;
