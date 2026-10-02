import { test } from "node:test";
import assert from "node:assert/strict";
import { HISTORY_START, kstToday, shiftDate, clampDate, historyTitle, historyMessage, runsTitle, dayStats, hourBuckets, bucketsText } from "../app/history-rules.ts";
import { TRIGGER_LABEL, secondsText } from "../app/status-rules.ts";

test("kstToday: KST 자정 기준", () => {
  assert.equal(kstToday(Date.parse("2026-09-10T14:59:59Z")), "2026-09-10");
  assert.equal(kstToday(Date.parse("2026-09-10T15:00:00Z")), "2026-09-11");
});

test("shiftDate · clampDate: 달·해 넘김, 범위 밖은 끝으로", () => {
  assert.equal(shiftDate("2026-09-30", 1), "2026-10-01");
  assert.equal(shiftDate("2027-01-01", -1), "2026-12-31");
  assert.equal(clampDate("2026-09-01", HISTORY_START, "2026-09-11"), HISTORY_START);
  assert.equal(clampDate("2026-09-12", HISTORY_START, "2026-09-11"), "2026-09-11");
  assert.equal(clampDate("2026-09-10", HISTORY_START, "2026-09-11"), "2026-09-10");
});

test("historyTitle: 오늘 / M월 D일", () => {
  assert.equal(historyTitle("2026-09-11", "2026-09-11"), "오늘 실행 이력");
  assert.equal(historyTitle("2026-09-05", "2026-09-11"), "9월 5일 실행 이력");
});

test("historyMessage: 불러오는 중·실패·연결 없음·빈 날·일부", () => {
  const base = { loading: false, error: false, source: "github", partial: false, count: 3, isToday: true };
  assert.equal(historyMessage(base), null);
  assert.deepEqual(historyMessage({ ...base, loading: true, source: null, count: 0 }), { text: "불러오는 중…", replacesTable: true });
  assert.equal(historyMessage({ ...base, error: true, source: null, count: 0 }).text, "이력을 불러오지 못했어요 · 잠시 뒤 다시 시도해 주세요");
  assert.equal(historyMessage({ ...base, source: "static", count: 0 }).text, "실행 이력은 GitHub 연결이 있을 때만 보여요.");
  assert.equal(historyMessage({ ...base, count: 0 }).text, "오늘은 아직 실행한 게 없어요.");
  assert.equal(historyMessage({ ...base, count: 0, isToday: false }).text, "이 날은 실행한 게 없어요.");
  assert.deepEqual(historyMessage({ ...base, partial: true }), { text: "GitHub 응답이 없어 일부만 보여요.", replacesTable: false });
});

test("TRIGGER_LABEL: 이 PC 실행", () => {
  assert.equal(TRIGGER_LABEL.local, "이 PC");
});

test("secondsText: 초·분·시간", () => {
  assert.equal(secondsText(45), "45초");
  assert.equal(secondsText(325), "5.4분");
  assert.equal(secondsText(51480), "14시간 18분");
});

test("dayStats · hourBuckets: 하루 집계와 KST 시간대별 횟수", () => {
  const items = [
    { status: "completed", conclusion: "success", startedAt: "2026-10-02T00:01:48Z", durationSec: 80 },   // KST 09시
    { status: "completed", conclusion: "success", startedAt: "2026-10-02T00:01:46Z", durationSec: 14 },   // KST 09시
    { status: "completed", conclusion: "failure", startedAt: "2026-10-01T21:00:35Z", durationSec: null }, // KST 06시
    { status: "completed", conclusion: "cancelled", startedAt: "2026-10-02T03:01:21Z", durationSec: null }, // 취소는 실패로 안 센다
    { status: "in_progress", conclusion: null, startedAt: null, durationSec: null },                        // 시각 없으면 막대에서 뺀다
  ];
  assert.deepEqual(dayStats(items), { runs: 5, ok: 2, failed: 1, avgSec: 47 });
  assert.deepEqual(dayStats([]), { runs: 0, ok: 0, failed: 0, avgSec: null });
  const b = hourBuckets(items);
  assert.equal(b.length, 24);
  assert.equal(b[9], 2); assert.equal(b[6], 1); assert.equal(b[12], 1);
  assert.equal(b.reduce((x, y) => x + y, 0), 4);
  assert.equal(bucketsText(b), "합계 4회 · 가장 많은 시간 09시");
  assert.equal(bucketsText(new Array(24).fill(0)), "");
  assert.equal(runsTitle("2026-10-02", "2026-10-02"), "오늘 실행");
  assert.equal(runsTitle("2026-10-01", "2026-10-02"), "10월 1일 실행");
});
