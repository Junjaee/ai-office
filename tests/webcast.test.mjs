import { test } from "node:test";
import assert from "node:assert/strict";
import {
  SPEECH_COOLDOWN_MS, WATCH_CHANNELS, activeChannels, fetchMeetings, isRunning, markerKey, meetingsFrom,
  nextMeetingLabel, resetMeetingsCache, shouldWakeSpeech, stateKey, watchWindow,
} from "../worker/webcast.ts";

// 2026-11-05 실제 캘린더 제목들 — 앞뒤 공백·대괄호가 제각각
const ITEMS = [
  { summary: "[예결위] 종합질의-13번째", start: { dateTime: "2026-11-05T10:00:00+09:00" }, end: { dateTime: "2026-11-05T18:00:00+09:00" } },
  { summary: " 예결위 전체회의(본관 제2회의장)", start: { dateTime: "2026-11-09T10:00:00+09:00" }, end: { dateTime: "2026-11-09T12:00:00+09:00" } },
  { summary: "재경위 전체회의", start: { dateTime: "2026-11-09T14:00:00+09:00" }, end: { dateTime: "2026-11-09T16:00:00+09:00" } },
  { summary: "본회의", start: { dateTime: "2026-11-06T14:00:00+09:00" }, end: { dateTime: "2026-11-06T16:00:00+09:00" } },
  { summary: "[참고] 예결위 전체회의", start: { date: "2026-11-10" }, end: { date: "2026-11-11" } },
];
const H = 60 * 60 * 1000;

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

test("재경위·예결위 제목만, 종일 일정은 무시", () => {
  const ms = meetingsFrom(ITEMS);
  assert.deepEqual(ms.map((m) => [m.title, m.xcodes]), [
    ["[예결위] 종합질의-13번째", ["21"]],
    ["예결위 전체회의(본관 제2회의장)", ["21"]],
    ["재경위 전체회의", ["65"]],
  ]);
  assert.equal(ms[0].startMs, Date.parse("2026-11-05T01:00:00Z"));
  assert.equal(WATCH_CHANNELS["재경위"], "65");
});

test("둘 다 든 제목은 두 채널", () => {
  const [m] = meetingsFrom([{ summary: "재경위·예결위 연석", start: { dateTime: "2026-11-05T10:00:00+09:00" }, end: { dateTime: "2026-11-05T11:00:00+09:00" } }]);
  assert.deepEqual(m.xcodes, ["65", "21"]);
});

test("감시 시간대 = 시작 10분 전 ~ 끝 3시간 뒤", () => {
  const [m] = meetingsFrom(ITEMS);
  assert.deepEqual(watchWindow(m), { fromMs: m.startMs - 10 * 60 * 1000, toMs: m.endMs + 3 * H });
});

test("activeChannels 는 xcode 별로 가장 늦은 끝", () => {
  const ms = meetingsFrom([
    { summary: "예결위 오전", start: { dateTime: "2026-11-05T10:00:00+09:00" }, end: { dateTime: "2026-11-05T12:00:00+09:00" } },
    { summary: "예결위 오후", start: { dateTime: "2026-11-05T14:00:00+09:00" }, end: { dateTime: "2026-11-05T18:00:00+09:00" } },
    { summary: "재경위", start: { dateTime: "2026-11-06T10:00:00+09:00" }, end: { dateTime: "2026-11-06T12:00:00+09:00" } },
  ]);
  const now = Date.parse("2026-11-05T02:30:00Z"); // KST 11:30 — 오전 예결위 안(오후 것은 아직 10분 전이 아니다)
  assert.deepEqual(activeChannels(ms, now), [{ xcode: "21", windowEndMs: Date.parse("2026-11-05T03:00:00Z") + 3 * H }]);
  // KST 14:30 — 오전(끝+3h=15:00)과 오후가 겹친다 → 오후 끝(18:00)+3h
  assert.deepEqual(activeChannels(ms, Date.parse("2026-11-05T05:30:00Z")), [{ xcode: "21", windowEndMs: Date.parse("2026-11-05T09:00:00Z") + 3 * H }]);
  assert.deepEqual(activeChannels(ms, Date.parse("2026-11-05T00:40:00Z")), []);   // KST 09:40 — 10분 전보다 이르다
  assert.equal(activeChannels(ms, Date.parse("2026-11-05T00:50:00Z")).length, 1);  // KST 09:50 — 시작 10분 전
});

test("queued 도 실행 중", () => {
  const runs = [
    { path: ".github/workflows/speech.yml", status: "queued", display_title: "speech · 21 · req-1" },
    { path: ".github/workflows/speech.yml", status: "completed", display_title: "speech · 65 · req-0" },
    { path: ".github/workflows/mail.yml", status: "in_progress", display_title: "mail · req-2" },
  ];
  assert.equal(isRunning(runs, "21"), true);
  assert.equal(isRunning(runs, "65"), false);
  assert.equal(isRunning([{ path: ".github/workflows/speech.yml", status: "in_progress", display_title: "speech · 65 · cron-1" }], "65"), true);
});

test("shouldWakeSpeech: 전부 참일 때만", () => {
  const now = 10 * SPEECH_COOLDOWN_MS;
  const base = { active: true, running: false, marked: false, lastRunMs: null, nowMs: now };
  assert.equal(shouldWakeSpeech(base), true);
  assert.equal(shouldWakeSpeech({ ...base, active: false }), false);
  assert.equal(shouldWakeSpeech({ ...base, running: true }), false);
  assert.equal(shouldWakeSpeech({ ...base, marked: true }), false);
  assert.equal(shouldWakeSpeech({ ...base, lastRunMs: now - SPEECH_COOLDOWN_MS + 1 }), false);
  assert.equal(shouldWakeSpeech({ ...base, lastRunMs: now - SPEECH_COOLDOWN_MS }), true);
});

test("nextMeetingLabel 형식", () => {
  const ms = meetingsFrom(ITEMS);
  assert.equal(nextMeetingLabel(ms, Date.parse("2026-11-06T00:00:00Z")), "11/9(월) 10:00 예결위 전체회의(본관 제2회의장)");
  assert.equal(nextMeetingLabel(ms, Date.parse("2026-11-09T02:00:00Z")), "11/9(월) 14:00 재경위 전체회의");
  assert.equal(nextMeetingLabel(ms, Date.parse("2026-12-01T00:00:00Z")), null);
});

test("R2 키 모양", () => {
  assert.equal(markerKey("skip", "2026-11-05", "21"), "speech/skip/2026-11-05-21");
  assert.equal(stateKey("DCM000021224390401"), "speech/state/DCM000021224390401.json");
});

test("fetchMeetings 는 캐시하고 오류는 던진다", async () => {
  resetMeetingsCache();
  const bad = fakeFetch([{ status: 500 }]);
  await assert.rejects(fetchMeetings("tok", bad, 1000), /캘린더/);
  const good = fakeFetch([{ body: { items: ITEMS } }]);
  const first = await fetchMeetings("tok", good, 1000);
  assert.equal(first.length, 3);
  assert.match(good.calls[0].url, /calendars\/1cad154d55cbc50b2d6f7205d0e583e845c725d89a89177461c814662e6815c2%40group\.calendar\.google\.com\/events/);
  assert.match(good.calls[0].url, /singleEvents=true/);
  assert.equal(good.calls[0].init.headers.authorization, "Bearer tok");
  const second = await fetchMeetings("tok", good, 2000);
  assert.equal(good.calls.length, 1);
  assert.deepEqual(second, first);
});
