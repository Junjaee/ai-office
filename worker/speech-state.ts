/** 회의 발언 요약(speech)의 작은 API — 실행 중 상태(R2)·오늘 표시·다음 회의.
 *
 * GET/PUT /api/speech/state?key=<xcgcd>          실행이 30초마다 저장하는 상태(보낸 묶음·열린 구간). 끊겨도 이어 받는다
 * GET/PUT /api/speech/mark?kind=skip|done&xcode=&date=   그날 "건너뜀"(이준석 위원 질의 없음)·"끝남" 표시 — Worker 가 다시 깨우지 않게
 * GET /api/speech/next                            캘린더의 다음 재경위·예결위 회의(카드 "다음 실행")와 캘린더 오류(화면 배너)
 *
 * 쓰기는 LIVE_TOKEN 이 있을 때만 X-Live-Token 을 검사한다(live.ts 와 같은 결정, 2026-09-29). 읽기는 자유.
 * 저장은 R2 버킷 LIVE(ai-office-live). 설계: docs/superpowers/specs/2026-11-05-회의-발언-요약-알림-design.md 8절.
 */
import { accessToken, googleCreds, type FetchLike } from "./gmail.ts";
import { tokenEquals, type R2Like } from "./live.ts";
import { fetchMeetings, markerKey, nextMeetingLabel, stateKey } from "./webcast.ts";

export type SpeechEnv = { LIVE?: R2Like; LIVE_TOKEN?: string };
export type SpeechNext = { nextMeeting: string | null; calendarError: string | null; checkedAt: string };

const MAX_BODY_BYTES = 1_000_000;
const KEY_RE = /^[A-Za-z0-9_-]{1,64}$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const XCODE_RE = /^\d{1,4}$/;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
}

function authorized(request: Request, env: SpeechEnv): boolean {
  if (!env.LIVE_TOKEN) return true;
  const token = request.headers.get("X-Live-Token") ?? "";
  return !!token && tokenEquals(token, env.LIVE_TOKEN);
}

export async function hasMarker(bucket: R2Like, kind: "skip" | "done", dateKst: string, xcode: string): Promise<boolean> {
  return (await bucket.get(markerKey(kind, dateKst, xcode))) !== null;
}

export async function handleSpeechState(request: Request, env: SpeechEnv): Promise<Response> {
  if (!env.LIVE) return json({ error: "live_unavailable" }, 503);
  const url = new URL(request.url);
  const isMark = url.pathname.endsWith("/mark");

  let r2key: string;
  if (isMark) {
    const kind = url.searchParams.get("kind") ?? "";
    const xcode = url.searchParams.get("xcode") ?? "";
    const date = url.searchParams.get("date") ?? "";
    if ((kind !== "skip" && kind !== "done") || !XCODE_RE.test(xcode) || !DATE_RE.test(date)) return json({ error: "bad_request" }, 400);
    r2key = markerKey(kind, date, xcode);
  } else {
    const key = url.searchParams.get("key") ?? "";
    if (!KEY_RE.test(key)) return json({ error: "bad_request" }, 400);
    r2key = stateKey(key);
  }

  if (request.method === "GET") {
    const obj = await env.LIVE.get(r2key);
    if (!obj) return json({ error: "not_found" }, 404);
    return new Response(await obj.text(), { status: 200, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
  }
  if (request.method !== "PUT") return json({ error: "method_not_allowed" }, 405);
  if (!authorized(request, env)) return json({ error: "unauthorized" }, 401);

  let body: string;
  if (isMark) {
    body = JSON.stringify({ at: new Date().toISOString() });
  } else {
    const text = await request.text();
    if (new TextEncoder().encode(text).byteLength > MAX_BODY_BYTES) return json({ error: "too_large" }, 413);
    try {
      JSON.parse(text);
    } catch {
      return json({ error: "bad_request" }, 400);
    }
    body = text;
  }
  await env.LIVE.put(r2key, body, { httpMetadata: { contentType: "application/json" } });
  return json({ ok: true });
}

/** 다음 회의 한 줄. 캘린더를 못 읽으면 nextMeeting null + calendarError(토큰 값은 담지 않는다) */
export async function speechNext(env: Record<string, unknown>, fetchImpl: FetchLike, nowMs: number): Promise<SpeechNext> {
  const checkedAt = new Date(nowMs).toISOString();
  const creds = googleCreds(env);
  if (!creds) return { nextMeeting: null, calendarError: "Worker 에 구글 토큰(GOOGLE_*)이 없음", checkedAt };
  try {
    const token = await accessToken(creds, fetchImpl, nowMs);
    const meetings = await fetchMeetings(token, fetchImpl, nowMs);
    return { nextMeeting: nextMeetingLabel(meetings, nowMs), calendarError: null, checkedAt };
  } catch (err) {
    return { nextMeeting: null, calendarError: err instanceof Error ? err.message : String(err), checkedAt };
  }
}
