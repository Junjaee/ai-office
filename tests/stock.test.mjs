import { test } from "node:test";
import assert from "node:assert/strict";
import { handleStock, boardKey, tickerKey, validTicker, applyWatch, WATCH_KEY, WATCH_MAX } from "../worker/stock.ts";

const ORIGIN = "https://ai-office.example.workers.dev";
const NOW = Date.parse("2026-10-05T01:00:00Z");

function fakeR2() {
  const store = new Map();
  return { store, async get(key) { const v = store.get(key); return v === undefined ? null : { text: async () => v }; }, async put(key, value) { store.set(key, value); } };
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
  assert.deepEqual(await body(r), { market: "us", board: null, watch: [], checkedAt: new Date(NOW).toISOString() });
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

test("없는 경로·메서드", async () => {
  const LIVE = fakeR2();
  assert.equal((await handleStock(new Request(`${ORIGIN}/api/stock/nope`), { LIVE }, deps)).status, 404);
  assert.equal((await handleStock(new Request(`${ORIGIN}/api/stock/watch`), { LIVE }, deps)).status, 405);
});
