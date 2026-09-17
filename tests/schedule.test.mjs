import { test } from "node:test";
import assert from "node:assert/strict";
import { MAIL_JOB, SCHEDULES, cronRequestId, dueJobs, matchesCron } from "../worker/schedule.ts";
// Node 의 타입 제거 실행은 확장자 없는 상대 import 를 못 읽으므로 사무실 파일을 직접 읽는다
import { workspace as assembly } from "../app/workspaces/assembly.ts";
import { workspace as home } from "../app/workspaces/home.ts";
import { workspace as side } from "../app/workspaces/side.ts";

const WORKSPACE_LIST = [assembly, home, side];

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
  assert.deepEqual(dueJobs(SCHEDULES, at("2026-09-17T05:23:00Z")), []);
});

test("상임위 메일은 예약표에 없다 — 새 메일이 왔을 때만 돈다 (사용자 결정 2026-09-17)", () => {
  assert.equal(SCHEDULES.some((j) => j.workflow === "mail.yml"), false);
  assert.equal(MAIL_JOB.workflow, "mail.yml");
  assert.equal(MAIL_JOB.cron, "");          // 시각이 아니라 지메일 확인 결과로 깨운다
});

test("같은 분에 같은 워크플로가 여러 번 맞으면 앞선 항목 하나만", () => {
  const jobs = [
    { workflow: "x.yml", cron: "30 21 * * *", inputs: { mode: "topics" }, note: "특정 시각" },
    { workflow: "x.yml", cron: "30 * * * *", inputs: { mode: "publish" }, note: "매시" },
  ];
  const both = dueJobs(jobs, at("2026-09-17T21:30:00Z"));   // 둘 다 맞는 시각
  assert.equal(both.length, 1);
  assert.deepEqual(both[0].inputs, { mode: "topics" });     // 앞선 것이 이긴다

  const onlyHourly = dueJobs(jobs, at("2026-09-17T03:30:00Z"));
  assert.deepEqual(onlyHourly[0].inputs, { mode: "publish" });
});

test("인스타는 예약에서 빠졌다 (사용자 결정 2026-09-17 — 사이트 ▶ 시작으로만)", () => {
  assert.equal(SCHEDULES.some((j) => j.workflow === "insta.yml"), false);
});

test("여러 자동화가 같은 분에 걸리면 모두 깨운다", () => {
  // 00:00 UTC(KST 09:00): 화성시·기사 수집(3시간마다)·가계부(6시간마다) 가 한꺼번에
  const morning = dueJobs(SCHEDULES, at("2026-09-17T00:00:00Z")).map((j) => j.workflow);
  assert.deepEqual(morning.sort(), ["hscity.yml", "ledger.yml", "news.yml"]);

  // 09:00 UTC(KST 18:00): 기사 수집만 (화성시는 아침 한 번, 가계부는 UTC 0/6/12/18)
  const evening = dueJobs(SCHEDULES, at("2026-09-17T09:00:00Z")).map((j) => j.workflow);
  assert.deepEqual(evening, ["news.yml"]);

  // 12:00 UTC(KST 21:00): 기사 수집·가계부
  const night = dueJobs(SCHEDULES, at("2026-09-17T12:00:00Z")).map((j) => j.workflow);
  assert.deepEqual(night.sort(), ["ledger.yml", "news.yml"]);
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


test("카드의 예약 문구와 실제 예약표가 어긋나지 않는다", () => {
  // 사무실 카드에 schedule 문구가 있으면 그 워크플로가 예약표에 있어야 한다.
  // (없으면 화면은 "예약"이라 하는데 아무도 깨우지 않고, "예약 놓침" 경고까지 뜬다)
  const scheduled = new Set(SCHEDULES.map((j) => j.workflow));
  for (const ws of WORKSPACE_LIST) {
    for (const def of ws.automations) {
      if (!def.schedule) continue;
      assert.ok(scheduled.has(def.workflow ?? ""),
        `${ws.id}/${def.id}: 카드에 "${def.schedule}" 이라 적혀 있는데 worker/schedule.ts 에 예약이 없다`);
    }
  }
});
