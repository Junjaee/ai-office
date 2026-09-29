import { test } from "node:test";
import assert from "node:assert/strict";
import { handleLive, liveKey, liveForStatus, tokenEquals, LIVE_MAX_BODY_BYTES } from "../worker/live.ts";
import { buildStatus, createRunApiStores } from "../worker/run-api.ts";

const ORIGIN = "https://ai-office.example.workers.dev";
const NOW = Date.parse("2026-09-29T01:30:00Z");
const workspaces = {
  home: {
    id: "home",
    automations: [
      { id: "ledger", workflow: "ledger.yml", tasks: [{ id: "collect" }] },
      { id: "orderbook", local: true, tasks: [{ id: "record" }, { id: "candles" }, { id: "flows" }] },
    ],
  },
};

function fakeR2() {
  const store = new Map();
  return {
    store,
    async get(key) {
      const v = store.get(key);
      return v === undefined ? null : { text: async () => v };
    },
    async put(key, value) {
      store.set(key, value);
    },
  };
}

const deps = () => ({ workspaces, now: () => NOW });
const post = (body, token = "secret-token-1234") =>
  new Request(`${ORIGIN}/api/live`, { method: "POST", headers: { "Content-Type": "application/json", ...(token ? { "X-Live-Token": token } : {}) }, body: typeof body === "string" ? body : JSON.stringify(body) });
const get = (ws, automation) => new Request(`${ORIGIN}/api/live?ws=${ws}&automation=${automation}`);

test("liveKey / tokenEquals", () => {
  assert.equal(liveKey("home", "orderbook", "record"), "live/home/orderbook/record.json");
  assert.ok(tokenEquals("abc", "abc"));
  assert.ok(!tokenEquals("abc", "abd"));
  assert.ok(!tokenEquals("abc", "abcd"));
  assert.ok(!tokenEquals("", "a"));
});

test("handleLive: 버킷 없으면 503", async () => {
  const res = await handleLive(get("home", "orderbook"), {}, deps());
  assert.equal(res.status, 503);
});

test("handleLive POST: LIVE_TOKEN 이 설정돼 있으면 토큰 없음·틀림 401, 없으면 토큰 없이도 받는다", async () => {
  const doc = { ws: "home", automation: "orderbook", task: "record", state: "running", at: "2026-09-29T10:29:55+09:00" };
  const locked = { LIVE: fakeR2(), LIVE_TOKEN: "secret-token-1234" };
  assert.equal((await handleLive(post(doc, ""), locked, deps())).status, 401);
  assert.equal((await handleLive(post(doc, "wrong"), locked, deps())).status, 401);
  assert.equal(locked.LIVE.store.size, 0);
  const open = { LIVE: fakeR2() };
  assert.equal((await handleLive(post(doc, ""), open, deps())).status, 200);
  assert.equal((await handleLive(post(doc, "anything"), open, deps())).status, 200);
  assert.equal(open.LIVE.store.size, 1);
});

test("handleLive POST: 없는 사무실·자동화·작업 404, 상태값 이상 400, 1MB 초과 413", async () => {
  const env = { LIVE: fakeR2(), LIVE_TOKEN: "secret-token-1234" };
  const doc = { ws: "home", automation: "orderbook", task: "record", state: "running", at: "2026-09-29T10:29:55+09:00" };
  assert.equal((await handleLive(post({ ...doc, ws: "nope" }), env, deps())).status, 404);
  assert.equal((await handleLive(post({ ...doc, automation: "ledger" }), env, deps())).status, 404, "workflow 자동화는 live 대상이 아님");
  assert.equal((await handleLive(post({ ...doc, task: "zzz" }), env, deps())).status, 404);
  assert.equal((await handleLive(post({ ...doc, state: "weird" }), env, deps())).status, 400);
  assert.equal((await handleLive(post("not json"), env, deps())).status, 400);
  assert.equal((await handleLive(post({ ...doc, board: "x".repeat(LIVE_MAX_BODY_BYTES) }), env, deps())).status, 413);
  assert.equal(env.LIVE.store.size, 0);
});

test("handleLive: 저장 → GET 이 작업별 문서를 돌려주고, /api/status 는 board 를 뺀 신호만 붙인다", async () => {
  const env = { LIVE: fakeR2(), LIVE_TOKEN: "secret-token-1234", ASSETS: { fetch: async () => new Response("", { status: 404 }) } };
  const board = { at: "x", items: [{ code: "005930" }] };
  const r1 = await handleLive(post({ ws: "home", automation: "orderbook", task: "record", state: "running", at: "2026-09-29T10:29:55+09:00", summary: "100종목", board }), env, deps());
  assert.equal(r1.status, 200);
  const r2 = await handleLive(post({ ws: "home", automation: "orderbook", task: "candles", state: "done", summary: "조각 120개" }), env, deps());
  assert.equal(r2.status, 200);
  assert.equal(env.LIVE.store.size, 2);

  const res = await handleLive(get("home", "orderbook"), env, deps());
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.deepEqual(Object.keys(body.tasks).sort(), ["candles", "flows", "record"]);
  assert.deepEqual(body.tasks.record.board, board);
  assert.equal(body.tasks.record.received_at, new Date(NOW).toISOString());
  assert.equal(body.tasks.candles.at, new Date(NOW).toISOString(), "at 이 없으면 서버 시각");
  assert.equal(body.tasks.flows, null);
  assert.equal((await handleLive(get("home", "ledger"), env, deps())).status, 404);

  const live = await liveForStatus(env, "home", workspaces.home);
  assert.deepEqual(Object.keys(live), ["orderbook"]);
  assert.equal(live.orderbook.record.board, undefined, "status 에는 board 를 넣지 않는다");
  assert.equal(live.orderbook.record.summary, "100종목");

  const status = await buildStatus("home", workspaces.home, ORIGIN, env, { ...createRunApiStores(), now: () => NOW, workspaces, github: null });
  assert.equal(status.live.orderbook.candles.state, "done");
  assert.equal("orderbook" in status.runs, false, "local 자동화는 GitHub run 을 찾지 않는다");
});
