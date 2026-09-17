/** Cloudflare Worker 진입점 — /api/run · /api/status · /api/history · /api/review 만 직접 처리하고 나머지는 vinext 에 넘긴다. */
import { handleImageOptimization, DEFAULT_DEVICE_SIZES, DEFAULT_IMAGE_SIZES } from "vinext/server/image-optimization";
import handler from "vinext/server/app-router-entry";
import { WORKSPACES } from "../app/workspaces/index";
import { GitHubClient } from "./github.ts";
import { createRunApiStores, handleHistory, handleReview, handleRun, handleStatus, type RunApiDeps } from "./run-api.ts";
import { MAIL_JOB, SCHEDULES, cronRequestId, dueJobs } from "./schedule.ts";
import { accessToken, coolEnough, googleCreds, newMailCount } from "./gmail.ts";

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

/** 마지막으로 메일 워크플로를 깨운 시각 — 실행이 도는 동안 또 깨우지 않는다(같은 isolate 안에서만 기억) */
let lastMailDispatchMs: number | null = null;

/** 새 상임위 메일이 있는지. 토큰이 없거나 확인에 실패하면 false(예약 처리는 그대로 진행한다). */
async function hasNewCommitteeMail(env: Env, nowMs: number): Promise<boolean> {
  const creds = googleCreds(env as unknown as Record<string, unknown>);
  if (!creds || !coolEnough(lastMailDispatchMs, nowMs)) return false;
  try {
    const token = await accessToken(creds, fetch, nowMs);
    return (await newMailCount(token, fetch)) > 0;
  } catch (err) {
    console.error(`메일 확인 실패 — ${err instanceof Error ? err.message : String(err)}`);
    return false;
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

    // 상임위 메일은 시각이 아니라 "새 메일이 왔을 때" 돈다 — 매분 지메일만 가볍게 확인한다
    if (await hasNewCommitteeMail(env, now.getTime())) jobs.push(MAIL_JOB);

    if (jobs.length === 0) return;

    const github = new GitHubClient(env.GITHUB_TOKEN);
    const requestId = cronRequestId(now);
    for (const job of jobs) {
      try {
        await github.dispatch(job.workflow, { request_id: requestId, ...(job.inputs ?? {}) });
        if (job.workflow === MAIL_JOB.workflow) lastMailDispatchMs = now.getTime();
        console.log(`예약 실행 요청: ${job.workflow} (${job.note}) ${requestId}`);
      } catch (err) {
        // 하나가 실패해도 나머지는 계속한다. 다음 분에 다시 기회가 온다
        console.error(`예약 실행 실패: ${job.workflow} — ${err instanceof Error ? err.message : String(err)}`);
      }
    }
  },
};

export default worker;
