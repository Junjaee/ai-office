import { test } from "node:test";
import assert from "node:assert/strict";
import { SCHEDULES, cronRequestId, dueJobs, matchesCron } from "../worker/schedule.ts";

const at = (iso) => new Date(iso);

test("cron: 모든 값(*)과 단순 값", () => {
  assert.equal(matchesCron("* * * * *", at("2026-09-17T05:24:00Z")), true);
  assert.equal(matchesCron("24 5 * * *", at("2026-09-17T05:24:00Z")), true);
  assert.equal(matchesCron("25 5 * * *", at("2026-09-17T05:24:00Z")), false);
  assert.equal(matchesCron("24 6 * * *", at("2026-09-17T05:24:00Z")), false);
});

test("cron: 간격(별표-슬래시-숫자)", () => {
  assert.equal(matchesCron("*/5 * * * *", at("2026-09-17T05:25:00Z")), true);
  assert.equal(matchesCron("*/5 * * * *", at("2026-09-17T05:26:00Z")), false);
  assert.equal(matchesCron("0 */3 * * *", at("2026-09-17T06:00:00Z")), true);
  assert.equal(matchesCron("0 */3 * * *", at("2026-09-17T07:00:00Z")), false);
  assert.equal(matchesCron("0 */6 * * *", at("2026-09-17T12:00:00Z")), true);
});

test("cron: 목록·범위·요일", () => {
  assert.equal(matchesCron("0,30 * * * *", at("2026-09-17T05:30:00Z")), true);
  assert.equal(matchesCron("0,30 * * * *", at("2026-09-17T05:31:00Z")), false);
  assert.equal(matchesCron("0 9-18 * * *", at("2026-09-17T09:00:00Z")), true);
  assert.equal(matchesCron("0 9-18 * * *", at("2026-09-17T19:00:00Z")), false);
  // 2026-09-17 은 목요일(4)
  assert.equal(matchesCron("0 8 * * 4", at("2026-09-17T08:00:00Z")), true);
  assert.equal(matchesCron("0 8 * * 5", at("2026-09-17T08:00:00Z")), false);
  // 일요일은 0 도 7 도 된다 (2026-09-20 은 일요일)
  assert.equal(matchesCron("0 8 * * 0", at("2026-09-20T08:00:00Z")), true);
  assert.equal(matchesCron("0 8 * * 7", at("2026-09-20T08:00:00Z")), true);
});

test("cron: 형식이 틀리면 false (예약을 멋대로 돌리지 않는다)", () => {
  assert.equal(matchesCron("", at("2026-09-17T05:24:00Z")), false);
  assert.equal(matchesCron("* * * *", at("2026-09-17T05:24:00Z")), false);
  assert.equal(matchesCron("헛소리 * * * *", at("2026-09-17T05:24:00Z")), false);
});

test("깨울 것 고르기: 안 맞으면 빈 목록", () => {
  assert.deepEqual(dueJobs(SCHEDULES, at("2026-09-17T05:23:00Z")), []);   // 5분 배수도 30분도 아님
});

test("깨울 것 고르기: 메일은 5분마다", () => {
  const due = dueJobs(SCHEDULES, at("2026-09-17T05:25:00Z"));
  assert.deepEqual(due.map((j) => j.workflow), ["mail.yml"]);
});

test("같은 분에 여러 개면 워크플로마다 하나만 — 인스타 후보가 게시 확인을 이긴다", () => {
  // 21:30 UTC = KST 06:30 — "30 21 * * *"(후보)와 "30 * * * *"(게시 확인)이 둘 다 맞는다
  const due = dueJobs(SCHEDULES, at("2026-09-17T21:30:00Z"));
  const insta = due.filter((j) => j.workflow === "insta.yml");
  assert.equal(insta.length, 1);
  assert.deepEqual(insta[0].inputs, { account: "all", mode: "topics" });

  // 보통 시각에는 게시 확인
  const noon = dueJobs(SCHEDULES, at("2026-09-17T03:30:00Z")).filter((j) => j.workflow === "insta.yml");
  assert.deepEqual(noon[0].inputs, { account: "all", mode: "publish" });
});

test("여러 자동화가 같은 분에 걸리면 모두 깨운다", () => {
  // 09:00 UTC(KST 18:00): 메일(5분마다)·화성시 저녁·기사 수집(3시간마다). 가계부는 UTC 0/6/12/18 이라 아님
  const evening = dueJobs(SCHEDULES, at("2026-09-17T09:00:00Z")).map((j) => j.workflow);
  assert.deepEqual(evening.sort(), ["hscity.yml", "mail.yml", "news.yml"]);

  // 12:00 UTC(KST 21:00): 메일·기사 수집·가계부
  const night = dueJobs(SCHEDULES, at("2026-09-17T12:00:00Z")).map((j) => j.workflow);
  assert.deepEqual(night.sort(), ["ledger.yml", "mail.yml", "news.yml"]);
});

test("예약표의 cron 은 전부 형식이 맞다", () => {
  for (const job of SCHEDULES) {
    assert.equal(job.cron.trim().split(/\s+/).length, 5, `${job.workflow} ${job.cron}`);
    assert.ok(job.note, `${job.workflow} 설명 없음`);
  }
});

test("요청 번호는 분 단위로 같다", () => {
  assert.equal(cronRequestId(at("2026-09-17T05:25:00Z")), "cron-202609170525");
  assert.equal(cronRequestId(at("2026-09-17T05:25:59Z")), "cron-202609170525");
  assert.notEqual(cronRequestId(at("2026-09-17T05:26:00Z")), "cron-202609170525");
});
