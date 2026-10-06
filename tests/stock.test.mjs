import { test } from "node:test";
import assert from "node:assert/strict";
import { handleStock, boardKey, tickerKey, lensKey, opinionKey, indexKey, lensHistKey, cleanOpinion, validTicker, applyWatch, WATCH_KEY, WATCH_MAX, OPINION_MAX } from "../worker/stock.ts";

const ORIGIN = "https://ai-office.example.workers.dev";
const NOW = Date.parse("2026-10-05T01:00:00Z");

function fakeR2() {
  const store = new Map();
  return { store, async get(key) { const v = store.get(key); return v === undefined ? null : { text: async () => v }; }, async put(key, value) { store.set(key, value); }, async list({ prefix }) { return { objects: [...store.keys()].filter((k) => k.startsWith(prefix)).map((key) => ({ key })), truncated: false }; } };
}
const deps = { now: () => NOW };
const get = (qs) => new Request(`${ORIGIN}/api/stock?${qs}`);
const post = (path, body, headers = {}) => new Request(`${ORIGIN}${path}`, { method: "POST", headers: { "Content-Type": "application/json", ...headers }, body: typeof body === "string" ? body : JSON.stringify(body) });
const body = async (r) => JSON.parse(await r.text());

test("키와 기호 형식", () => {
  assert.equal(boardKey("us"), "stock/us/board.json");
  assert.equal(tickerKey("us", "BRK-B"), "stock/us/t/BRK-B.json");
  assert.ok(validTicker("us", "ORCL") && validTicker("us", "BRK-B") && validTicker("kr", "005930"));
  assert.ok(!validTicker("us", "orcl") && !validTicker("us", "../x") && !validTicker("us", "") && !validTicker("kr", "5930") && !validTicker("jp", "7203"));
});

test("applyWatch: 담기·빼기·중복·상한", () => {
  assert.deepEqual(applyWatch(["A"], "B", "add"), { list: ["A", "B"] });
  assert.deepEqual(applyWatch(["A", "B"], "B", "add"), { list: ["A", "B"] });
  assert.deepEqual(applyWatch(["A", "B"], "A", "remove"), { list: ["B"] });
  const full = Array.from({ length: WATCH_MAX }, (_, i) => `T${i}`);
  assert.deepEqual(applyWatch(full, "NEW", "add"), { list: full, error: "watch_full" });
});

test("저장소가 없으면 503", async () => {
  const r = await handleStock(get("market=us&view=board"), {}, deps);
  assert.equal(r.status, 503);
});

test("판: 저장 전에는 board null, 관심 목록은 빈 배열", async () => {
  const LIVE = fakeR2();
  const r = await handleStock(get("market=us&view=board"), { LIVE }, deps);
  assert.equal(r.status, 200);
  assert.deepEqual(await body(r), { market: "us", board: null, watch: [], lensDays: 0, checkedAt: new Date(NOW).toISOString() });
  assert.equal((await handleStock(get("market=xx&view=board"), { LIVE }, deps)).status, 400);
});

test("ingest → 판·종목 읽기", async () => {
  const LIVE = fakeR2();
  const board = { market: "us", as_of: "2026-10-02", rows: [{ t: "ORCL" }] };
  assert.equal((await handleStock(post("/api/stock/ingest", { market: "us", kind: "board", doc: board }), { LIVE }, deps)).status, 200);
  assert.equal((await handleStock(post("/api/stock/ingest", { market: "us", kind: "ticker", ticker: "ORCL", doc: { rec: { t: "ORCL" } } }), { LIVE }, deps)).status, 200);
  assert.deepEqual((await body(await handleStock(get("market=us&view=board"), { LIVE }, deps))).board, board);
  const t = await body(await handleStock(get("market=us&ticker=ORCL"), { LIVE }, deps));
  assert.deepEqual(t.doc, { rec: { t: "ORCL" } });
  assert.equal(t.watched, false);
  assert.equal((await body(await handleStock(get("market=us&ticker=NONE"), { LIVE }, deps))).doc, null);
  assert.equal((await handleStock(get("market=us&ticker=bad!"), { LIVE }, deps)).status, 400);
});

test("ingest: 형식 오류 400, 토큰이 설정돼 있으면 검사", async () => {
  const LIVE = fakeR2();
  assert.equal((await handleStock(post("/api/stock/ingest", "not json"), { LIVE }, deps)).status, 400);
  assert.equal((await handleStock(post("/api/stock/ingest", { market: "us", kind: "ticker", doc: {} }), { LIVE }, deps)).status, 400);
  assert.equal((await handleStock(post("/api/stock/ingest", { market: "us", kind: "nope", doc: {} }), { LIVE }, deps)).status, 400);
  const env = { LIVE, LIVE_TOKEN: "secret-token-1234" };
  assert.equal((await handleStock(post("/api/stock/ingest", { market: "us", kind: "board", doc: {} }), env, deps)).status, 401);
  assert.equal((await handleStock(post("/api/stock/ingest", { market: "us", kind: "board", doc: {} }, { "X-Live-Token": "secret-token-1234" }), env, deps)).status, 200);
});

test("관심 담기·빼기: 저장되고 판·종목 응답에 반영, 다른 출처는 403", async () => {
  const LIVE = fakeR2();
  let r = await handleStock(post("/api/stock/watch", { market: "us", ticker: "NVDA", action: "add" }), { LIVE }, deps);
  assert.deepEqual(await body(r), { ok: true, watch: ["NVDA"] });
  await handleStock(post("/api/stock/watch", { market: "us", ticker: "ORCL", action: "add" }), { LIVE }, deps);
  assert.deepEqual(JSON.parse(LIVE.store.get(WATCH_KEY)).us, ["NVDA", "ORCL"]);
  assert.deepEqual((await body(await handleStock(get("market=us&view=watch"), { LIVE }, deps))).watch, ["NVDA", "ORCL"]);
  assert.equal((await body(await handleStock(get("market=us&ticker=ORCL"), { LIVE }, deps))).watched, true);
  r = await handleStock(post("/api/stock/watch", { market: "us", ticker: "NVDA", action: "remove" }), { LIVE }, deps);
  assert.deepEqual((await body(r)).watch, ["ORCL"]);
  assert.equal((await handleStock(post("/api/stock/watch", { market: "us", ticker: "bad ticker", action: "add" }), { LIVE }, deps)).status, 400);
  assert.equal((await handleStock(post("/api/stock/watch", { market: "us", ticker: "X", action: "toggle" }), { LIVE }, deps)).status, 400);
  assert.equal((await handleStock(post("/api/stock/watch", { market: "us", ticker: "X", action: "add" }, { Origin: "https://evil.example" }), { LIVE }, deps)).status, 403);
});

test("관심 쓰기: 읽기·해석에 실패하면 503 이고 아무것도 쓰지 않는다", async () => {
  const put = [];
  const throwing = { async get() { throw new Error("r2 down"); }, async put(k) { put.push(k); } };
  const bad = { async get() { return { text: async () => "{not json" }; }, async put(k) { put.push(k); } };
  for (const LIVE of [throwing, bad]) {
    const r = await handleStock(post("/api/stock/watch", { market: "us", ticker: "NVDA", action: "add" }), { LIVE }, deps);
    assert.equal(r.status, 503);
    assert.deepEqual(await body(r), { error: "stock_unavailable" });
  }
  assert.deepEqual(put, []);
  // 목록이 아직 없는 것(빈 목록)은 정상: 첫 담기는 저장된다
  assert.equal((await handleStock(post("/api/stock/watch", { market: "us", ticker: "NVDA", action: "add" }), { LIVE: fakeR2() }, deps)).status, 200);
});

test("시장 이름: constructor 같은 상속 속성은 차단", async () => {
  const LIVE = fakeR2();
  for (const market of ["constructor", "toString", "__proto__"]) {
    // validTicker 는 에러 없이 false 를 반환한다
    assert.equal(validTicker(market, "X"), false);
    // GET 판·종목은 400
    assert.equal((await handleStock(get(`market=${market}&view=board`), { LIVE }, deps)).status, 400);
    assert.equal((await handleStock(get(`market=${market}&ticker=X`), { LIVE }, deps)).status, 400);
    // POST ingest 는 400 이고 저장하지 않는다
    assert.equal((await handleStock(post("/api/stock/ingest", { market, kind: "board", doc: {} }), { LIVE }, deps)).status, 400);
    const keyPrefix = `stock/${market}/`;
    const stored = Array.from(LIVE.store.keys()).filter((k) => k.startsWith(keyPrefix));
    assert.equal(stored.length, 0, `이 시장 아래 저장된 키가 있으면 안 됨: ${stored.join(", ")}`);
    // POST watch 는 400
    assert.equal((await handleStock(post("/api/stock/watch", { market, ticker: "X", action: "add" }), { LIVE }, deps)).status, 400);
  }
});

test("ingest kind=lens 는 날짜별 파일로 저장하고 날짜가 이상하면 거절한다", async () => {
  const LIVE = fakeR2();
  const ok = await handleStock(post("/api/stock/ingest", { market: "us", kind: "lens", date: "2026-10-05", doc: { hits: {} } }), { LIVE }, deps);
  assert.equal(ok.status, 200);
  assert.equal(lensKey("us", "2026-10-05"), "stock/lens-log/us/2026-10-05.json");
  assert.ok(LIVE.store.has("stock/lens-log/us/2026-10-05.json"));
  for (const date of ["2026-1-5", "../x", "", undefined, 20261005, "2026-10-05\n"]) {
    const bad = await handleStock(post("/api/stock/ingest", { market: "us", kind: "lens", date, doc: { hits: {} } }), { LIVE }, deps);
    assert.equal(bad.status, 400);
  }
  assert.equal(LIVE.store.size, 1);
});

test("ingest kind=lens: 실제 달력 날짜이고 최근(10일 전~2일 뒤)이어야 한다", async () => {
  const LIVE = fakeR2();
  const send = (date) => handleStock(post("/api/stock/ingest", { market: "us", kind: "lens", date, doc: { hits: {} } }), { LIVE }, deps);
  // 달력에 없는 날, 너무 오래된 날, 너무 먼 미래 → 400 이고 저장 없음
  for (const date of ["9999-99-99", "2026-13-45", "2026-02-30", "2026-09-05", "2026-10-10"]) assert.equal((await send(date)).status, 400, date);
  assert.equal(LIVE.store.size, 0);
  // 오늘(NOW 의 날)과 어제는 받는다
  assert.equal((await send("2026-10-05")).status, 200);
  assert.equal((await send("2026-10-04")).status, 200);
  assert.equal(LIVE.store.size, 2);
});

test("판 응답에 그 시장의 관점 기록 일수가 붙는다", async () => {
  const LIVE = fakeR2();
  for (const d of ["2026-10-01", "2026-10-02"]) await handleStock(post("/api/stock/ingest", { market: "us", kind: "lens", date: d, doc: {} }), { LIVE }, deps);
  await handleStock(post("/api/stock/ingest", { market: "kr", kind: "lens", date: "2026-10-01", doc: {} }), { LIVE }, deps);
  const r = await handleStock(get("market=us&view=board"), { LIVE }, deps);
  assert.equal((await body(r)).lensDays, 2);
});

test("기록 일수를 세지 못해도 판은 그대로 준다", async () => {
  const LIVE = fakeR2();
  LIVE.list = async () => { throw new Error("boom"); };
  const r = await handleStock(get("market=us&view=board"), { LIVE }, deps);
  assert.equal(r.status, 200);
  assert.equal((await body(r)).lensDays, 0);
});

test("없는 경로·메서드", async () => {
  const LIVE = fakeR2();
  assert.equal((await handleStock(new Request(`${ORIGIN}/api/stock/nope`), { LIVE }, deps)).status, 404);
  assert.equal((await handleStock(new Request(`${ORIGIN}/api/stock/watch`), { LIVE }, deps)).status, 405);
});

// ---- 3단계: 해석 저장·읽기, 지수·관점 기록 ----
const OP = { price: 142.3, as_of: "2026-10-02", next_earn: "2026-12-10", verdict: "  한 줄 결론  ", good: [{ text: "좋은 점", src: "재무" }], bad: [{ text: "나쁜 점", src: "시세" }], watch: ["다음 실적"] };
const cleaned = { ...OP, verdict: "한 줄 결론" };
const withTicker = () => { const LIVE = fakeR2(); LIVE.store.set(tickerKey("us", "ORCL"), JSON.stringify({ rec: { t: "ORCL" } })); return LIVE; };   // 종목 자료가 올라와 있는 저장 공간
const opPost = (opinion, extra = {}, headers = {}) => post("/api/stock/opinion", { market: "us", ticker: "ORCL", opinion, ...extra }, headers);

test("cleanOpinion: 정상은 정리해서 돌려주고 모르는 키는 버린다", () => {
  assert.deepEqual(cleanOpinion(OP), cleaned);
  assert.deepEqual(cleanOpinion({ ...OP, next_earn: null, watch: [], id: "x", rating: "buy", good: [{ text: " a ", src: "뉴스", extra: 1 }] }), { ...cleaned, next_earn: null, watch: [], good: [{ text: "a", src: "뉴스" }] });
  assert.equal(OPINION_MAX, 20);
  assert.equal(opinionKey("us", "ORCL"), "stock/opinions/us/ORCL.json");
  assert.equal(indexKey("kr"), "stock/kr/index.json");
  assert.equal(lensHistKey("us"), "stock/us/lens-history.json");
});

test("cleanOpinion: 어긋나면 null", () => {
  const pts = (n, text = "t", src = "재무") => Array.from({ length: n }, () => ({ text, src }));
  const bads = [
    null, [], "x", { ...OP, verdict: undefined }, { ...OP, verdict: "   " }, { ...OP, verdict: "가".repeat(301) }, { ...OP, verdict: 5 },
    { ...OP, good: "x" }, { ...OP, good: [] }, { ...OP, good: pts(7) }, { ...OP, bad: [] }, { ...OP, bad: pts(7) },
    { ...OP, good: pts(1, "t", "소문") }, { ...OP, good: pts(1, "t", null) }, { ...OP, good: pts(1, "가".repeat(301)) }, { ...OP, good: pts(1, "  ") }, { ...OP, good: ["x"] },
    { ...OP, price: 0 }, { ...OP, price: -1 }, { ...OP, price: "142" }, { ...OP, price: NaN }, { ...OP, price: Infinity },
    { ...OP, as_of: "2026-10-2" }, { ...OP, as_of: "2026-02-30" }, { ...OP, as_of: undefined },
    { ...OP, next_earn: undefined }, { ...OP, next_earn: "내년" }, { ...OP, next_earn: "2026-13-01" },
    { ...OP, watch: undefined }, { ...OP, watch: Array(7).fill("w") }, { ...OP, watch: ["가".repeat(201)] }, { ...OP, watch: [""] }, { ...OP, watch: [3] },
  ];
  bads.forEach((b, i) => assert.equal(cleanOpinion(b), null, `bad #${i}`));
  assert.ok(cleanOpinion({ ...OP, verdict: "가".repeat(300), good: pts(6, "가".repeat(300)), watch: Array(6).fill("가".repeat(200)) }));
});

test("해석 저장: id 는 서버 시각, 최근 것이 앞, 20개까지, 같은 밀리초도 id 가 겹치지 않는다", async () => {
  const LIVE = withTicker();
  const r = await handleStock(opPost(OP), { LIVE }, deps);
  assert.equal(r.status, 200);
  const first = await body(r);
  assert.deepEqual(first, { ok: true, id: new Date(NOW).toISOString() });
  assert.deepEqual(JSON.parse(LIVE.store.get("stock/opinions/us/ORCL.json")).items, [{ id: first.id, ...cleaned }]);
  const second = await body(await handleStock(opPost({ ...OP, verdict: "둘째" }), { LIVE }, deps));
  assert.ok(second.id > first.id);
  const items = JSON.parse(LIVE.store.get("stock/opinions/us/ORCL.json")).items;
  assert.deepEqual(items.map((i) => i.verdict), ["둘째", "한 줄 결론"]);
  for (let i = 0; i < 25; i++) await handleStock(opPost({ ...OP, verdict: `v${i}` }), { LIVE }, deps);
  const all = JSON.parse(LIVE.store.get("stock/opinions/us/ORCL.json")).items;
  assert.equal(all.length, OPINION_MAX);
  assert.equal(all[0].verdict, "v24");
  assert.equal(new Set(all.map((i) => i.id)).size, OPINION_MAX);
});

test("해석 저장: 잘못된 기호·시장·본문 400, 토큰, 큰 본문 413, 없는 메서드 405", async () => {
  const LIVE = fakeR2();
  for (const b of [{ ticker: "orcl" }, { ticker: "../x" }, { market: "jp" }, { market: "constructor" }, { ticker: 5 }, { opinion: { ...OP, verdict: "" } }, { opinion: null }]) {
    const req = post("/api/stock/opinion", { market: "us", ticker: "ORCL", opinion: OP, ...b });
    assert.equal((await handleStock(req, { LIVE }, deps)).status, 400, JSON.stringify(b));
  }
  assert.equal((await handleStock(post("/api/stock/opinion", "not json"), { LIVE }, deps)).status, 400);
  assert.equal(LIVE.store.size, 0);
  LIVE.store.set(tickerKey("us", "ORCL"), "{}");
  const env = { LIVE, LIVE_TOKEN: "secret-token-1234" };
  assert.equal((await handleStock(opPost(OP), env, deps)).status, 401);
  assert.equal((await handleStock(opPost(OP, {}, { "X-Live-Token": "secret-token-1234" }), env, deps)).status, 200);
  assert.equal((await handleStock(opPost(OP, { pad: "x".repeat(20_000) }), { LIVE }, deps)).status, 413);
  assert.equal((await handleStock(new Request(`${ORIGIN}/api/stock/opinion`), { LIVE }, deps)).status, 405);
  // 스크립트가 부르는 길이라 다른 출처 검사는 하지 않는다
  assert.equal((await handleStock(opPost(OP, {}, { Origin: "https://evil.example" }), { LIVE }, deps)).status, 200);
});

test("해석 저장: 자료가 올라와 있지 않은 종목은 404 이고 아무것도 쓰지 않는다", async () => {
  const LIVE = fakeR2();
  const r = await handleStock(opPost(OP), { LIVE }, deps);
  assert.equal(r.status, 404);
  assert.deepEqual(await body(r), { error: "not_found" });
  assert.equal(LIVE.store.size, 0);
  LIVE.store.set(tickerKey("us", "ORCL"), "{}");
  assert.equal((await handleStock(opPost(OP, { ticker: "MSFT" }), { LIVE }, deps)).status, 404);   // 다른 종목 자료로는 열리지 않는다
  assert.equal((await handleStock(opPost(OP), { LIVE }, deps)).status, 200);
});

test("해석 저장: 읽기·해석에 실패하면 503 이고 쓰지 않는다", async () => {
  const put = [];
  const throwing = { async get() { throw new Error("r2 down"); }, async put(k) { put.push(k); } };
  const broken = { async get() { return { text: async () => "{not json" }; }, async put(k) { put.push(k); } };
  const oddShape = { async get() { return { text: async () => '{"items":"x"}' }; }, async put(k) { put.push(k); } };
  for (const LIVE of [throwing, broken, oddShape]) {
    const r = await handleStock(opPost(OP), { LIVE }, deps);
    assert.equal(r.status, 503);
    assert.deepEqual(await body(r), { error: "stock_unavailable" });
  }
  assert.deepEqual(put, []);
});

test("종목 응답의 opinions: 없으면 [], 저장된 것도 다시 걸러서", async () => {
  const LIVE = fakeR2();
  assert.deepEqual((await body(await handleStock(get("market=us&ticker=ORCL"), { LIVE }, deps))).opinions, []);
  LIVE.store.set("stock/opinions/us/ORCL.json", JSON.stringify({ items: [
    { id: "2026-10-05T01:00:00.000Z", ...cleaned, rating: "buy" },
    { id: "2026-10-04T01:00:00.000Z", ...cleaned, verdict: "" },
    { ...cleaned },
    { id: 7, ...cleaned },
    "junk",
  ] }));
  assert.deepEqual((await body(await handleStock(get("market=us&ticker=ORCL"), { LIVE }, deps))).opinions, [{ id: "2026-10-05T01:00:00.000Z", ...cleaned }]);
  LIVE.store.set("stock/opinions/us/ORCL.json", "{broken");
  assert.deepEqual((await body(await handleStock(get("market=us&ticker=ORCL"), { LIVE }, deps))).opinions, []);
});

test("ingest kind=index·lenshist 와 읽기 view", async () => {
  const LIVE = fakeR2();
  assert.deepEqual(await body(await handleStock(get("market=us&view=index"), { LIVE }, deps)), { market: "us", index: null });
  assert.deepEqual(await body(await handleStock(get("market=us&view=lenshist"), { LIVE }, deps)), { market: "us", history: null });
  const index = { t: "SPY", closes: [["2025-10-06", 571.2]] };
  const history = { days: { "2026-10-05": { value: ["AAA"] } } };
  assert.equal((await handleStock(post("/api/stock/ingest", { market: "us", kind: "index", doc: index }), { LIVE }, deps)).status, 200);
  assert.equal((await handleStock(post("/api/stock/ingest", { market: "us", kind: "lenshist", doc: history }), { LIVE }, deps)).status, 200);
  assert.ok(LIVE.store.has("stock/us/index.json") && LIVE.store.has("stock/us/lens-history.json"));
  assert.deepEqual(await body(await handleStock(get("market=us&view=index"), { LIVE }, deps)), { market: "us", index });
  assert.deepEqual(await body(await handleStock(get("market=us&view=lenshist"), { LIVE }, deps)), { market: "us", history });
  for (const kind of ["index", "lenshist"]) {
    assert.equal((await handleStock(post("/api/stock/ingest", { market: "us", kind, doc: [1] }), { LIVE }, deps)).status, 400);
    assert.equal((await handleStock(post("/api/stock/ingest", { market: "us", kind, doc: "x" }), { LIVE }, deps)).status, 400);
    assert.equal((await handleStock(post("/api/stock/ingest", { market: "us", kind, doc: { pad: "x".repeat(2_000_000) } }), { LIVE }, deps)).status, 413);
  }
});

test("view=lenshist: 읽기 실패는 503", async () => {
  for (const text of [null, "{not json"]) {
    const LIVE = { async get() { if (text === null) throw new Error("down"); return { text: async () => text }; }, async put() {} };
    const r = await handleStock(get("market=us&view=lenshist"), { LIVE }, deps);
    assert.equal(r.status, 503);
  }
});
