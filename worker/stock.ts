// /api/stock — 주식 분석 자료(판·종목 한 장)와 관심 목록. R2(LIVE 버킷)의 stock/ 아래에 둔다.
//
// GET  /api/stock?market=us&view=watch|board     → 관심 목록 / 판 요약 + 관심 목록
// GET  /api/stock?market=us&ticker=ORCL          → 종목 한 장 자료
// POST /api/stock/watch   {market, ticker, action:"add"|"remove"}   화면에서 담고 빼기(다른 출처는 막는다)
// POST /api/stock/ingest  {market, kind:"board"|"ticker"|"lens", ticker?, date?, doc}   수집 프로그램(automations/analyst)이 보냄
//
// 공개 저장소에는 종목·관심 목록을 두지 않으려고 여기에 둔다. 사이트에 로그인이 없으므로 주소를 아는 사람은 볼 수 있다
// (/api/live 와 같은 조건, 사용자 결정 2026-09-29). ingest 는 LIVE_TOKEN 이 설정돼 있을 때만 토큰을 검사한다.
import { tokenEquals, type R2Like } from "./live.ts";
import { isCrossOrigin } from "./run-api.ts";

export type StockEnv = { LIVE?: R2Like; LIVE_TOKEN?: string };

export const WATCH_KEY = "stock/watchlist.json";
export const WATCH_MAX = 100;
export const INGEST_MAX_BYTES = 2_000_000;
const TICKER_RE: Record<string, RegExp> = { us: /^[A-Z][A-Z0-9.\-]{0,9}$/, kr: /^[0-9]{6}$/ };

export const boardKey = (market: string) => `stock/${market}/board.json`;
export const tickerKey = (market: string, ticker: string) => `stock/${market}/t/${ticker}.json`;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
export const lensKey = (market: string, date: string) => `stock/lens-log/${market}/${date}.json`;

/** 그 시장의 관점 기록 파일 수. 세지 못하면 0 (판을 막지 않는다) */
async function countLensDays(bucket: R2Like, market: string): Promise<number> {
  if (!bucket.list) return 0;
  try {
    let n = 0;
    let cursor: string | undefined;
    do {
      const page = await bucket.list({ prefix: `stock/lens-log/${market}/`, cursor });
      n += page.objects.length;
      cursor = page.truncated ? page.cursor : undefined;
    } while (cursor);
    return n;
  } catch {
    return 0;
  }
}

/** 시장 이름이 TICKER_RE 의 자기 속성인지 확인 (constructor 같은 상속 속성 차단) */
function isMarket(market: string): boolean {
  return Object.prototype.hasOwnProperty.call(TICKER_RE, market);
}

export function validTicker(market: string, ticker: string): boolean {
  if (!isMarket(market)) return false;
  const re = TICKER_RE[market];
  return re.test(ticker);
}

/** 관심 목록에 담거나 뺀 새 목록. 가득 차면 목록은 그대로 두고 error 를 붙인다 */
export function applyWatch(list: string[], ticker: string, action: "add" | "remove"): { list: string[]; error?: "watch_full" } {
  if (action === "remove") return { list: list.filter((t) => t !== ticker) };
  if (list.includes(ticker)) return { list };
  if (list.length >= WATCH_MAX) return { list, error: "watch_full" };
  return { list: [...list, ticker] };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" } });
}

async function readJson(bucket: R2Like, key: string): Promise<unknown | null> {
  try {
    const obj = await bucket.get(key);
    return obj ? JSON.parse(await obj.text()) : null;
  } catch {
    return null;
  }
}

function asObject(doc: unknown): Record<string, unknown> {
  return doc && typeof doc === "object" && !Array.isArray(doc) ? (doc as Record<string, unknown>) : {};
}

/** 읽기용: 못 읽으면 빈 목록으로 본다 */
async function readWatch(bucket: R2Like): Promise<Record<string, unknown>> {
  return asObject(await readJson(bucket, WATCH_KEY));
}

/** 쓰기용: 없는 것(빈 목록)은 정상, 읽기·해석 실패는 null — 이때 덮어쓰면 목록이 통째로 사라진다 */
async function readWatchStrict(bucket: R2Like): Promise<Record<string, unknown> | null> {
  try {
    const obj = await bucket.get(WATCH_KEY);
    return obj ? asObject(JSON.parse(await obj.text())) : {};
  } catch {
    return null;
  }
}

function watchOf(all: Record<string, unknown>, market: string): string[] {
  const list = all[market];
  return Array.isArray(list) ? list.filter((t): t is string => typeof t === "string" && validTicker(market, t)) : [];
}

async function readBody(request: Request, max: number): Promise<Record<string, unknown> | Response> {
  if (Number(request.headers.get("Content-Length") ?? "0") > max) return json({ error: "too_large" }, 413);
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > max) return json({ error: "too_large" }, 413);
  try {
    const parsed = JSON.parse(text);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return json({ error: "bad_request" }, 400);
    return parsed as Record<string, unknown>;
  } catch {
    return json({ error: "bad_request" }, 400);
  }
}

export async function handleStock(request: Request, env: StockEnv, deps: { now: () => number }): Promise<Response> {
  const url = new URL(request.url);
  const bucket = env.LIVE;
  if (!bucket) return json({ error: "stock_unavailable" }, 503);
  const checkedAt = new Date(deps.now()).toISOString();

  if (url.pathname === "/api/stock") {
    if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405);
    const market = url.searchParams.get("market") ?? "";
    if (!isMarket(market)) return json({ error: "bad_request" }, 400);
    const watch = watchOf(await readWatch(bucket), market);
    const ticker = url.searchParams.get("ticker");
    if (ticker !== null) {
      if (!validTicker(market, ticker)) return json({ error: "bad_request" }, 400);
      return json({ market, ticker, doc: await readJson(bucket, tickerKey(market, ticker)), watched: watch.includes(ticker), checkedAt });
    }
    const view = url.searchParams.get("view") ?? "board";
    if (view === "watch") return json({ market, watch });
    if (view === "board") return json({ market, board: await readJson(bucket, boardKey(market)), watch, lensDays: await countLensDays(bucket, market), checkedAt });
    return json({ error: "bad_request" }, 400);
  }

  if (url.pathname === "/api/stock/watch") {
    if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
    if (isCrossOrigin(request)) return json({ error: "forbidden" }, 403);
    const body = await readBody(request, 2_000);
    if (body instanceof Response) return body;
    const { market, ticker, action } = body;
    if (typeof market !== "string" || typeof ticker !== "string" || !validTicker(market, ticker) || (action !== "add" && action !== "remove")) {
      return json({ error: "bad_request" }, 400);
    }
    const all = await readWatchStrict(bucket);
    if (!all) return json({ error: "stock_unavailable" }, 503);
    const next = applyWatch(watchOf(all, market), ticker, action);
    if (next.error) return json({ error: next.error }, 409);
    await bucket.put(WATCH_KEY, JSON.stringify({ ...all, [market]: next.list, updated_at: checkedAt }), { httpMetadata: { contentType: "application/json" } });
    return json({ ok: true, watch: next.list });
  }

  if (url.pathname === "/api/stock/ingest") {
    if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
    if (env.LIVE_TOKEN) {
      const token = request.headers.get("X-Live-Token") ?? "";
      if (!token || !tokenEquals(token, env.LIVE_TOKEN)) return json({ error: "unauthorized" }, 401);
    }
    const body = await readBody(request, INGEST_MAX_BYTES);
    if (body instanceof Response) return body;
    const { market, kind, ticker, date, doc } = body;
    if (typeof market !== "string" || !isMarket(market) || !doc || typeof doc !== "object") return json({ error: "bad_request" }, 400);
    let key: string;
    if (kind === "board") key = boardKey(market);
    else if (kind === "ticker" && typeof ticker === "string" && validTicker(market, ticker)) key = tickerKey(market, ticker);
    else if (kind === "lens" && typeof date === "string" && DATE_RE.test(date)) key = lensKey(market, date);
    else return json({ error: "bad_request" }, 400);
    await bucket.put(key, JSON.stringify(doc), { httpMetadata: { contentType: "application/json" } });
    return json({ ok: true });
  }

  return json({ error: "not_found" }, 404);
}
