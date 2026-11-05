import { test } from "node:test";
import assert from "node:assert/strict";
import { handleSpeechState, hasMarker, speechNext } from "../worker/speech-state.ts";
import { resetMeetingsCache } from "../worker/webcast.ts";
import { resetTokenCache } from "../worker/gmail.ts";

const ORIGIN = "https://ai-office.example.workers.dev";

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

function req(path, init) {
  return new Request(`${ORIGIN}${path}`, init);
}

test("state PUT 뒤 GET 이 같은 JSON", async () => {
  const env = { LIVE: fakeR2() };
  const doc = { version: 1, sent: [1, 2], open: null };
  const put = await handleSpeechState(req("/api/speech/state?key=DCM000021224390401", { method: "PUT", body: JSON.stringify(doc) }), env);
  assert.equal(put.status, 200);
  assert.ok(env.LIVE.store.has("speech/state/DCM000021224390401.json"));
  const got = await handleSpeechState(req("/api/speech/state?key=DCM000021224390401"), env);
  assert.equal(got.status, 200);
  assert.deepEqual(await got.json(), doc);
});

test("없는 key 는 404, 잘못된 key 는 400", async () => {
  const env = { LIVE: fakeR2() };
  assert.equal((await handleSpeechState(req("/api/speech/state?key=none"), env)).status, 404);
  assert.equal((await handleSpeechState(req("/api/speech/state?key=../x"), env)).status, 400);
  assert.equal((await handleSpeechState(req("/api/speech/state"), env)).status, 400);
  assert.equal((await handleSpeechState(req("/api/speech/state?key=a", { method: "PUT", body: "not json" }), env)).status, 400);
  assert.equal((await handleSpeechState(req("/api/speech/state?key=a"), {})).status, 503);
});

test("LIVE_TOKEN 이 있으면 PUT 은 토큰 검사", async () => {
  const env = { LIVE: fakeR2(), LIVE_TOKEN: "secret" };
  const body = JSON.stringify({ a: 1 });
  assert.equal((await handleSpeechState(req("/api/speech/state?key=k", { method: "PUT", body }), env)).status, 401);
  assert.equal((await handleSpeechState(req("/api/speech/state?key=k", { method: "PUT", body, headers: { "X-Live-Token": "secret" } }), env)).status, 200);
  assert.equal((await handleSpeechState(req("/api/speech/state?key=k"), env)).status, 200);   // 읽기는 토큰 없이
});

test("mark PUT 뒤 hasMarker true, 다른 날짜는 false", async () => {
  const env = { LIVE: fakeR2() };
  assert.equal((await handleSpeechState(req("/api/speech/mark?kind=skip&xcode=21&date=2026-11-05", { method: "PUT" }), env)).status, 200);
  assert.equal(await hasMarker(env.LIVE, "skip", "2026-11-05", "21"), true);
  assert.equal(await hasMarker(env.LIVE, "skip", "2026-11-06", "21"), false);
  assert.equal(await hasMarker(env.LIVE, "done", "2026-11-05", "21"), false);
  assert.equal((await handleSpeechState(req("/api/speech/mark?kind=skip&xcode=21&date=2026-11-05"), env)).status, 200);
  assert.equal((await handleSpeechState(req("/api/speech/mark?kind=done&xcode=21&date=2026-11-05"), env)).status, 404);
  assert.equal((await handleSpeechState(req("/api/speech/mark?kind=bad&xcode=21&date=2026-11-05", { method: "PUT" }), env)).status, 400);
  assert.equal((await handleSpeechState(req("/api/speech/mark?kind=skip&xcode=21&date=20261105", { method: "PUT" }), env)).status, 400);
});

test("speechNext: 캘린더 실패면 calendarError 문구, 토큰 값은 없음", async () => {
  resetMeetingsCache();
  resetTokenCache();
  const env = { GOOGLE_CLIENT_ID: "a", GOOGLE_CLIENT_SECRET: "b", GOOGLE_REFRESH_TOKEN: "refresh-secret" };
  const steps = [{ body: { access_token: "tok", expires_in: 3600 } }, { status: 403 }];
  const fetchImpl = async () => {
    const s = steps.shift();
    return new Response(JSON.stringify(s.body ?? {}), { status: s.status ?? 200 });
  };
  const r = await speechNext(env, fetchImpl, Date.parse("2026-11-06T00:00:00Z"));
  assert.equal(r.nextMeeting, null);
  assert.match(r.calendarError, /캘린더 읽기 실패 \(HTTP 403\)/);
  assert.ok(!r.calendarError.includes("refresh-secret") && !r.calendarError.includes("tok"));
  const none = await speechNext({}, fetchImpl, 0);
  assert.equal(none.nextMeeting, null);
  assert.match(none.calendarError, /구글 토큰/);
});

test("speechNext: 성공하면 다음 회의 문구", async () => {
  resetMeetingsCache();
  resetTokenCache();
  const env = { GOOGLE_CLIENT_ID: "a", GOOGLE_CLIENT_SECRET: "b", GOOGLE_REFRESH_TOKEN: "c" };
  const steps = [
    { body: { access_token: "tok", expires_in: 3600 } },
    { body: { items: [{ summary: "예결위 전체회의", start: { dateTime: "2026-11-09T10:00:00+09:00" }, end: { dateTime: "2026-11-09T12:00:00+09:00" } }] } },
  ];
  const fetchImpl = async () => {
    const s = steps.shift();
    return new Response(JSON.stringify(s.body ?? {}), { status: s.status ?? 200 });
  };
  const r = await speechNext(env, fetchImpl, Date.parse("2026-11-06T00:00:00Z"));
  assert.equal(r.nextMeeting, "11/9(월) 10:00 예결위 전체회의");
  assert.equal(r.calendarError, null);
});
