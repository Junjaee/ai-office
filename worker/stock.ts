// /api/stock — 주식 분석 자료(판·종목 한 장)와 관심 목록. R2(LIVE 버킷)의 stock/ 아래에 둔다.
//
// GET  /api/stock?market=us&view=watch|board     → 관심 목록 / 판 요약 + 관심 목록
// GET  /api/stock?market=us&ticker=ORCL          → 종목 한 장 자료
// POST /api/stock/watch   {market, ticker, action:"add"|"remove"}   화면에서 담고 빼기(다른 출처는 막는다)
// GET  /api/stock?market=us&ticker=ORCL          → (위 응답에 opinions: 저장된 해석 최대 20개, 최근 것부터)
// GET  /api/stock?market=us&view=index           → {market, index}  지수(SPY 등) 1년 종가, 없으면 null
// GET  /api/stock?market=us&view=lenshist        → {market, history}  관점 채점용 기록, 못 읽으면 503(쓰는 쪽이 덮어쓰지 않게)
// POST /api/stock/opinion {market, ticker, opinion:{price, as_of, next_earn, verdict, good, bad, watch}} → {ok, id}   사람이 요청한 해석 저장
// POST /api/stock/ingest  {market, kind:"board"|"ticker"|"lens"|"index"|"lenshist", ticker?, date?, doc}   수집 프로그램(automations/analyst)이 보냄
//
// 공개 저장소에는 종목·관심 목록을 두지 않으려고 여기에 둔다. 사이트에 로그인이 없으므로 주소를 아는 사람은 볼 수 있다
// (/api/live 와 같은 조건, 사용자 결정 2026-09-29). ingest 는 LIVE_TOKEN 이 설정돼 있을 때만 토큰을 검사한다.
import { tokenEquals, type R2Like } from "./live.ts";
import { isCrossOrigin } from "./run-api.ts";

export type StockEnv = { LIVE?: R2Like; LIVE_TOKEN?: string };

export const WATCH_KEY = "stock/watchlist.json";
export const WATCH_MAX = 100;
export const INGEST_MAX_BYTES = 2_000_000;
export const OPINION_MAX = 20;
const OPINION_MAX_BYTES = 20_000;
const TICKER_RE: Record<string, RegExp> = { us: /^[A-Z][A-Z0-9.\-]{0,9}$/, kr: /^[0-9][0-9A-Z]{5}$/ };

export const boardKey = (market: string) => `stock/${market}/board.json`;
export const tickerKey = (market: string, ticker: string) => `stock/${market}/t/${ticker}.json`;
export const opinionKey = (market: string, ticker: string) => `stock/opinions/${market}/${ticker}.json`;
export const indexKey = (market: string) => `stock/${market}/index.json`;
export const lensHistKey = (market: string) => `stock/${market}/lens-history.json`;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
export const lensKey = (market: string, date: string) => `stock/lens-log/${market}/${date}.json`;
const DAY_MS = 86_400_000;

/** 실제 달력에 있는 날이고 now 기준 10일 전 ~ 2일 뒤 안일 때만 (인증 없는 입구라 키가 끝없이 늘지 않게) */
function validLensDate(date: string, now: number): boolean {
  if (!DATE_RE.test(date)) return false;
  const t = Date.parse(`${date}T00:00:00Z`);
  return Number.isFinite(t) && new Date(t).toISOString().slice(0, 10) === date && t > now - 10 * DAY_MS && t < now + 2 * DAY_MS;
}

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

/** 쓰기·검증용 읽기: 없는 것은 {ok:true, doc:null}, 읽기·해석 실패는 {ok:false} — 이때 덮어쓰면 기록이 통째로 사라진다 */
async function readStrict(bucket: R2Like, key: string): Promise<{ ok: true; doc: unknown | null } | { ok: false }> {
  try {
    const obj = await bucket.get(key);
    return { ok: true, doc: obj ? JSON.parse(await obj.text()) : null };
  } catch {
    return { ok: false };
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
  const r = await readStrict(bucket, WATCH_KEY);
  return r.ok ? asObject(r.doc) : null;
}

export type OpinionPoint = { text: string; src: "재무" | "시세" | "뉴스" | "전망" };
export type Opinion = { price: number; as_of: string; next_earn: string | null; verdict: string; good: OpinionPoint[]; bad: OpinionPoint[]; watch: string[] };
const SRC = new Set(["재무", "시세", "뉴스", "전망"]);

/** 실제 달력에 있는 YYYY-MM-DD */
function isDate(v: unknown): v is string {
  if (typeof v !== "string" || !DATE_RE.test(v)) return false;
  const t = Date.parse(`${v}T00:00:00Z`);
  return Number.isFinite(t) && new Date(t).toISOString().slice(0, 10) === v;
}

/** 앞뒤 공백을 뗀 글자(코드 포인트) 수가 1..max 이면 그 글자, 아니면 null */
function text(v: unknown, max: number): string | null {
  if (typeof v !== "string") return null;
  const s = v.trim();
  return s && [...s].length <= max ? s : null;
}

function points(v: unknown): OpinionPoint[] | null {
  if (!Array.isArray(v) || v.length < 1 || v.length > 6) return null;
  const out: OpinionPoint[] = [];
  for (const p of v) {
    if (!p || typeof p !== "object" || Array.isArray(p)) return null;
    const t = text((p as Record<string, unknown>).text, 300);
    const src = (p as Record<string, unknown>).src;
    if (t === null || typeof src !== "string" || !SRC.has(src)) return null;
    out.push({ text: t, src: src as OpinionPoint["src"] });
  }
  return out;
}

/** 해석 입력(저장 전·읽은 뒤 모두)을 검사해 아는 키만 담은 새 값으로. 하나라도 어긋나면 null */
export function cleanOpinion(input: unknown): Opinion | null {
  if (!input || typeof input !== "object" || Array.isArray(input)) return null;
  const o = input as Record<string, unknown>;
  const verdict = text(o.verdict, 300);
  const good = points(o.good);
  const bad = points(o.bad);
  if (verdict === null || !good || !bad) return null;
  if (typeof o.price !== "number" || !Number.isFinite(o.price) || o.price <= 0) return null;
  if (!isDate(o.as_of) || !(o.next_earn === null || isDate(o.next_earn))) return null;
  if (!Array.isArray(o.watch) || o.watch.length > 6) return null;
  const watch: string[] = [];
  for (const w of o.watch) {
    const t = text(w, 200);
    if (t === null) return null;
    watch.push(t);
  }
  return { price: o.price, as_of: o.as_of, next_earn: o.next_earn, verdict, good, bad, watch };
}

/** 저장된 파일에서 꺼낸 목록: 검사를 다시 통과하고 문자열 id 가 있는 것만 */
function storedOpinions(doc: unknown): (Opinion & { id: string })[] {
  const items = asObject(doc).items;
  if (!Array.isArray(items)) return [];
  const out: (Opinion & { id: string })[] = [];
  for (const it of items) {
    const c = cleanOpinion(it);
    const id = asObject(it).id;
    if (c && typeof id === "string") out.push({ ...c, id });
  }
  return out;
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
      const opinions = storedOpinions(await readJson(bucket, opinionKey(market, ticker)));
      return json({ market, ticker, doc: await readJson(bucket, tickerKey(market, ticker)), watched: watch.includes(ticker), opinions, checkedAt });
    }
    const view = url.searchParams.get("view") ?? "board";
    if (view === "watch") return json({ market, watch });
    if (view === "board") return json({ market, board: await readJson(bucket, boardKey(market)), watch, lensDays: await countLensDays(bucket, market), checkedAt });
    if (view === "index") return json({ market, index: await readJson(bucket, indexKey(market)) });
    if (view === "lenshist") {
      const r = await readStrict(bucket, lensHistKey(market));
      return r.ok ? json({ market, history: r.doc }) : json({ error: "stock_unavailable" }, 503);
    }
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

  if (url.pathname === "/api/stock/opinion") {
    if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405);
    if (env.LIVE_TOKEN) {
      const token = request.headers.get("X-Live-Token") ?? "";
      if (!token || !tokenEquals(token, env.LIVE_TOKEN)) return json({ error: "unauthorized" }, 401);
    }
    const body = await readBody(request, OPINION_MAX_BYTES);
    if (body instanceof Response) return body;
    const { market, ticker } = body;
    const opinion = cleanOpinion(body.opinion);
    if (typeof market !== "string" || typeof ticker !== "string" || !validTicker(market, ticker) || !opinion) return json({ error: "bad_request" }, 400);
    // 자료가 올라와 있는 종목에만 쓴다 — 아무 기호나 보내 저장 공간을 채우지 못하게(읽기 실패는 모른다는 뜻이라 503)
    const known = await readStrict(bucket, tickerKey(market, ticker));
    if (!known.ok) return json({ error: "stock_unavailable" }, 503);
    if (known.doc === null) return json({ error: "not_found" }, 404);
    const key = opinionKey(market, ticker);
    const cur = await readStrict(bucket, key);
    if (!cur.ok || (cur.doc !== null && !Array.isArray(asObject(cur.doc).items))) return json({ error: "stock_unavailable" }, 503);
    const items = storedOpinions(cur.doc);
    // 같은 밀리초에 둘이 들어와도 id 는 서로 다르고 나중 것이 더 늦다
    const ids = new Set(items.map((i) => i.id));
    let t = deps.now();
    while (ids.has(new Date(t).toISOString())) t += 1;
    const id = new Date(t).toISOString();
    await bucket.put(key, JSON.stringify({ items: [{ id, ...opinion }, ...items].slice(0, OPINION_MAX) }), { httpMetadata: { contentType: "application/json" } });
    return json({ ok: true, id });
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
    if ((kind === "index" || kind === "lenshist") && Array.isArray(doc)) return json({ error: "bad_request" }, 400);
    let key: string;
    if (kind === "board") key = boardKey(market);
    else if (kind === "ticker" && typeof ticker === "string" && validTicker(market, ticker)) key = tickerKey(market, ticker);
    else if (kind === "index") key = indexKey(market);
    else if (kind === "lenshist") key = lensHistKey(market);
    else if (kind === "lens" && typeof date === "string" && validLensDate(date, deps.now())) key = lensKey(market, date);
    else return json({ error: "bad_request" }, 400);
    await bucket.put(key, JSON.stringify(doc), { httpMetadata: { contentType: "application/json" } });
    return json({ ok: true });
  }

  return json({ error: "not_found" }, 404);
}
