// /api/live — 이 PC 에서 도는 자동화(local)가 보내는 살아있음 신호·실시간 화면 자료. R2(LIVE 버킷)에 작업별 JSON 하나씩 덮어쓴다.
//
// POST /api/live  헤더 X-Live-Token: <LIVE_TOKEN>  본문 {ws, automation, task, state, at, summary?, started_at?, finished_at?, board?}
//   → R2 `live/<ws>/<automation>/<task>.json` 에 저장(≤ 1MB). 사무실 설정에 있는 local 자동화의 작업만 받는다.
// GET  /api/live?ws=…&automation=…  → {ws, automation, tasks: {<task>: 문서|null}, checkedAt}  (실시간 화면이 5초마다 읽음)
// /api/status 는 readLiveDocs() 로 같은 문서를 읽되 큰 board 는 빼고 넘긴다(직원 상태 판정용).
import type { WorkspaceLike } from "./run-api.ts";

export type R2Like = {
  get(key: string): Promise<{ text(): Promise<string> } | null>;
  put(key: string, value: string, options?: unknown): Promise<unknown>;
};

export type LiveEnv = { LIVE?: R2Like; LIVE_TOKEN?: string };

export const LIVE_MAX_BODY_BYTES = 1_000_000;
const LIVE_STATES = new Set(["running", "done", "error", "idle"]);

export function liveKey(ws: string, automation: string, task: string): string {
  return `live/${ws}/${automation}/${task}.json`;
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
}

/** 길이가 달라도 같은 시간이 걸리게 비교한다(토큰 비교) */
export function tokenEquals(a: string, b: string): boolean {
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i % Math.max(1, x.length)] ?? 0) ^ (y[i % Math.max(1, y.length)] ?? 0);
  return diff === 0;
}

type LocalDef = { id: string; tasks: { id: string }[] };

function localDef(workspace: WorkspaceLike | undefined, automation: string): LocalDef | null {
  const def = workspace?.automations.find((a) => a.id === automation);
  if (!def || !def.local || def.workflow) return null;
  return { id: def.id, tasks: def.tasks ?? [] };
}

/** 작업별 문서를 읽는다. strip=true 면 큰 필드(board)를 뺀다 */
export async function readLiveDocs(bucket: R2Like, ws: string, def: LocalDef, strip: boolean): Promise<Record<string, unknown | null>> {
  const out: Record<string, unknown | null> = {};
  await Promise.all(
    def.tasks.map(async (t) => {
      try {
        const obj = await bucket.get(liveKey(ws, def.id, t.id));
        if (!obj) {
          out[t.id] = null;
          return;
        }
        const doc = JSON.parse(await obj.text()) as Record<string, unknown>;
        if (strip) delete doc.board;
        out[t.id] = doc;
      } catch {
        out[t.id] = null;
      }
    }),
  );
  return out;
}

/** /api/status 용: 사무실의 local 자동화마다 (board 뺀) 신호 문서 */
export async function liveForStatus(env: LiveEnv, ws: string, workspace: WorkspaceLike): Promise<Record<string, Record<string, unknown | null>>> {
  const out: Record<string, Record<string, unknown | null>> = {};
  if (!env.LIVE) return out;
  for (const a of workspace.automations) {
    const def = localDef(workspace, a.id);
    if (def) out[a.id] = await readLiveDocs(env.LIVE, ws, def, true);
  }
  return out;
}

export async function handleLive(request: Request, env: LiveEnv, deps: { workspaces: Record<string, WorkspaceLike>; now: () => number }): Promise<Response> {
  const url = new URL(request.url);
  if (!env.LIVE) return json({ error: "live_unavailable" }, 503);

  if (request.method === "GET") {
    const ws = url.searchParams.get("ws") ?? "";
    const automation = url.searchParams.get("automation") ?? "";
    const def = localDef(deps.workspaces[ws], automation);
    if (!def) return json({ error: "not_found" }, 404);
    const tasks = await readLiveDocs(env.LIVE, ws, def, false);
    return json({ ws, automation, tasks, checkedAt: new Date(deps.now()).toISOString() });
  }

  if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
  // 토큰은 선택: Worker 비밀값 LIVE_TOKEN 이 있을 때만 검사한다(사용자 결정 2026-09-29 — 나만 보는 사이트라 자물쇠 없이 운영).
  // 없으면 주소를 아는 누구나 써 넣을 수 있다. 받는 건 사무실 설정에 있는 local 자동화의 작업 문서(≤1MB)뿐.
  if (env.LIVE_TOKEN) {
    const token = request.headers.get("X-Live-Token") ?? "";
    if (!token || !tokenEquals(token, env.LIVE_TOKEN)) return json({ error: "unauthorized" }, 401);
  }
  const declared = Number(request.headers.get("Content-Length") ?? "0");
  if (declared > LIVE_MAX_BODY_BYTES) return json({ error: "too_large" }, 413);
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > LIVE_MAX_BODY_BYTES) return json({ error: "too_large" }, 413);
  let body: Record<string, unknown>;
  try {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return json({ error: "bad_request" }, 400);
    body = parsed as Record<string, unknown>;
  } catch {
    return json({ error: "bad_request" }, 400);
  }
  const { ws, automation, task, state, at } = body;
  if (typeof ws !== "string" || typeof automation !== "string" || typeof task !== "string" || typeof state !== "string" || !LIVE_STATES.has(state)) {
    return json({ error: "bad_request" }, 400);
  }
  const def = localDef(deps.workspaces[ws], automation);
  if (!def || !def.tasks.some((t) => t.id === task)) return json({ error: "not_found" }, 404);
  const receivedAt = new Date(deps.now()).toISOString();
  const doc = { ...body, at: typeof at === "string" && at ? at : receivedAt, received_at: receivedAt };
  await env.LIVE.put(liveKey(ws, automation, task), JSON.stringify(doc), { httpMetadata: { contentType: "application/json" } });
  return json({ ok: true, at: doc.at });
}
