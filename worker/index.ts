/** Cloudflare Worker 진입점 — /api/run · /api/status 만 직접 처리하고 나머지는 vinext 에 넘긴다. */
import { handleImageOptimization, DEFAULT_DEVICE_SIZES, DEFAULT_IMAGE_SIZES } from "vinext/server/image-optimization";
import handler from "vinext/server/app-router-entry";
import { WORKSPACES } from "../app/workspaces/index";
import { GitHubClient } from "./github.ts";
import { createRunApiStores, handleRun, handleStatus, type RunApiDeps } from "./run-api.ts";

interface Env {
  ASSETS: Fetcher;
  /** fine-grained PAT (Cloudflare Secret / .dev.vars). 값은 절대 응답·로그에 내보내지 않는다 */
  GITHUB_TOKEN?: string;
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

const worker = {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/api/run") {
      return handleRun(request, env, depsFor(env));
    }

    if (url.pathname === "/api/status") {
      return handleStatus(request, env, depsFor(env));
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
};

export default worker;
