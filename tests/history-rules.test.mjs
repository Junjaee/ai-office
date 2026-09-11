import { test } from "node:test";
import assert from "node:assert/strict";
import { HISTORY_START, kstToday, shiftDate, clampDate, historyTitle, historyMessage } from "../app/history-rules.ts";
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
