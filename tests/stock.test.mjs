import { test } from "node:test";
import assert from "node:assert/strict";
import { handleStock, boardKey, tickerKey, lensKey, validTicker, applyWatch, WATCH_KEY, WATCH_MAX } from "../worker/stock.ts";

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
