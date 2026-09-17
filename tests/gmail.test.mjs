import { test } from "node:test";
import assert from "node:assert/strict";
import {
  MAIL_COOLDOWN_MS, MAIL_WATCH_QUERY, accessToken, coolEnough, countMessages, googleCreds,
  newMailCount, resetTokenCache,
} from "../worker/gmail.ts";

const CREDS = { clientId: "id", clientSecret: "secret", refreshToken: "refresh" };

function fakeFetch(steps) {
  const calls = [];
  const impl = async (url, init) => {
    calls.push({ url, init });
    const step = steps.shift();
    if (step instanceof Error) throw step;
    return new Response(JSON.stringify(step.body ?? {}), { status: step.status ?? 200 });
  };
  impl.calls = calls;
  return impl;
}

test("구글 토큰 3개가 다 있어야 확인한다", () => {
  assert.deepEqual(googleCreds({ GOOGLE_CLIENT_ID: "a", GOOGLE_CLIENT_SECRET: "b", GOOGLE_REFRESH_TOKEN: "c" }),
    { clientId: "a", clientSecret: "b", refreshToken: "c" });
  assert.equal(googleCreds({ GOOGLE_CLIENT_ID: "a", GOOGLE_CLIENT_SECRET: "b" }), null);
  assert.equal(googleCreds({}), null);
});

test("검색어는 라벨이 안 붙은 국회 메일만 (파이썬이 붙이면 다음부터 안 잡힌다)", () => {
  assert.match(MAIL_WATCH_QUERY, /from:assembly\.go\.kr/);
  assert.match(MAIL_WATCH_QUERY, /-label:"재경위"/);
  assert.match(MAIL_WATCH_QUERY, /-label:"예결위"/);
});

test("쉬는 시간: 방금 깨웠으면 또 깨우지 않는다", () => {
  const now = 1_000_000;
  assert.equal(coolEnough(null, now), true);                          // 처음이면 바로
  assert.equal(coolEnough(now - 1000, now), false);                   // 1초 전에 깨움 → 쉰다
  assert.equal(coolEnough(now - MAIL_COOLDOWN_MS, now), true);        // 쉬는 시간이 지나면 다시
});

test("건수 세기: 목록이 있으면 길이, 없으면 추정치", () => {
  assert.equal(countMessages({ messages: [{ id: "a" }, { id: "b" }] }), 2);
  assert.equal(countMessages({ resultSizeEstimate: 7 }), 7);
  assert.equal(countMessages({ resultSizeEstimate: 0 }), 0);
  assert.equal(countMessages({}), 0);
  assert.equal(countMessages(null), 0);
});

test("액세스 토큰은 받아서 캐시한다 (매분 다시 받지 않는다)", async () => {
  resetTokenCache();
  const impl = fakeFetch([{ body: { access_token: "TOK", expires_in: 3600 } }]);
  const now = 1_000_000;

  assert.equal(await accessToken(CREDS, impl, now), "TOK");
  assert.equal(await accessToken(CREDS, impl, now + 60_000), "TOK");   // 캐시 사용 — 호출 1번뿐
  assert.equal(impl.calls.length, 1);
  assert.match(impl.calls[0].init.body, /grant_type=refresh_token/);
});

test("토큰이 만료되면 다시 받는다", async () => {
  resetTokenCache();
  const impl = fakeFetch([
    { body: { access_token: "T1", expires_in: 120 } },
    { body: { access_token: "T2", expires_in: 3600 } },
  ]);
  const now = 1_000_000;
  assert.equal(await accessToken(CREDS, impl, now), "T1");
  assert.equal(await accessToken(CREDS, impl, now + 121_000), "T2");
});

test("토큰 갱신 실패는 예외 (부르는 쪽에서 건너뛴다)", async () => {
  resetTokenCache();
  const impl = fakeFetch([{ status: 400, body: { error: "invalid_grant" } }]);
  await assert.rejects(() => accessToken(CREDS, impl, 1), /구글 토큰 갱신 실패/);
});

test("새 메일 세기: 검색어를 붙이고 토큰을 헤더에 넣는다", async () => {
  const impl = fakeFetch([{ body: { messages: [{ id: "m1" }] } }]);
  assert.equal(await newMailCount("TOK", impl), 1);
  assert.match(impl.calls[0].url, /gmail\.googleapis\.com/);
  assert.match(impl.calls[0].url, /q=from%3Aassembly\.go\.kr/);
  assert.equal(impl.calls[0].init.headers.authorization, "Bearer TOK");
});

test("새 메일이 없으면 0", async () => {
  const impl = fakeFetch([{ body: { resultSizeEstimate: 0 } }]);
  assert.equal(await newMailCount("TOK", impl), 0);
});

test("지메일 오류는 예외", async () => {
  const impl = fakeFetch([{ status: 403, body: {} }]);
  await assert.rejects(() => newMailCount("TOK", impl), /지메일 확인 실패 \(HTTP 403\)/);
});
