// node automations/checkup/extension/rules.test.mjs
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

new Function(readFileSync(new URL("./rules.js", import.meta.url), "utf8"))();
const R = globalThis.checkupRules;

// 월요일(여는 날)·주중·일요일 어디서 봐도 '다음에 열리는 주'가 나온다
const week = ["2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03", "2026-12-04"];
assert.deepEqual(R.nextWeekDates(new Date(2026, 10, 23)), week);            // 월 — 오늘 연다
assert.deepEqual(R.nextWeekDates(new Date(2026, 10, 22)), week);            // 일 — 내일 연다
assert.deepEqual(R.nextWeekDates(new Date(2026, 10, 17)), week);            // 화 — 다음 월요일에 연다
assert.deepEqual(R.nextWeekDates(new Date(2026, 10, 16))[0], "2026-11-23");

assert.equal(R.to12h("13:30"), "1:30");
assert.equal(R.to12h("10:30"), "10:30");
assert.deepEqual(R.list(" 10:30, 13:30  14:30 "), ["10:30", "13:30", "14:30"]);

const slots = [{ text: "10:30", disabled: true }, { text: "11:30", disabled: false },
               { text: "1:30", disabled: false }];
assert.equal(R.pickSlot(slots, ["10:30", "13:30"]), 2);      // 1순위 마감 → 2순위
assert.equal(R.pickSlot(slots, ["10:30"]), -1);              // 원하는 칸만 — 없으면 안 잡는다
assert.equal(R.pickSlot(slots, []), 1);                      // 비우면 빈 칸 아무거나

const cells = [{ day: 1, disabled: true, cls: "unselectable" }, { day: 30, disabled: false, cls: "closed" },
               { day: 1, disabled: false, cls: "" }];
assert.deepEqual(R.findDay(cells, 1), { index: 2, status: "open" });        // 끝줄의 다음 달 1일
assert.equal(R.findDay(cells, 30).status, "closed");
assert.equal(R.findDay(cells, 9).status, "missing");

assert.equal(new Date(R.targetEpoch("08:59:59", new Date(2026, 10, 23, 8, 0))).getSeconds(), 59);
assert.equal(R.targetEpoch("아홉시", Date.now()), null);

// 시간표 응답 — 실제 응답 모양(2026-11-16 교정 클리닉 11-24)
const slot = (t, booked, biz = true) => ({ unitStartTime: t, unitBookingCount: booked, unitStock: 1,
  isUnitBusinessDay: biz, isUnitSaleDay: true, isSaleDay: true, isHoliday: false });
const hourly = [slot("2026-11-24 00:00:00", 0, false), slot("2026-11-24 10:30:00", 1), slot("2026-11-24 13:30:00", 0),
                slot("2026-11-25 10:30:00", 0), slot("2026-11-25 09:30:00", 0)];
const two = ["2026-11-24", "2026-11-25"];
assert.deepEqual(R.pickFromSchedule(hourly, two, []), { date: "2026-11-24", time: "13:30" });      // 영업 안 하는 00:00 은 뺀다
assert.deepEqual(R.pickFromSchedule(hourly, two, ["10:30"]), { date: "2026-11-25", time: "10:30" }); // 날짜가 먼저, 없으면 다음 날
assert.deepEqual(R.pickFromSchedule(hourly, ["2026-11-25"], ["9:30"]), { date: "2026-11-25", time: "09:30" });
assert.equal(R.pickFromSchedule(hourly, ["2026-11-24"], ["10:30"]), null);                        // 찬 칸

// 고르기 보기 — 병원 설정값 그대로(2026-11-22)
assert.equal(R.pickOption(["있음", "없음(예약불가/확인시 통보없이 취소됨)"]), 0);   // "확인"이 들어 있어도 없음은 안 고른다
assert.equal(R.pickOption(["비동의", "동의"]), 1);
assert.equal(R.pickOption(["동의"]), 0);
assert.equal(R.pickOption(["네 확인했습니다."]), 0);                              // 교정 클리닉
assert.equal(R.pickOption(["아니요", "네, 확인했습니다"]), 1);
assert.equal(R.pickOption(["오전", "오후"]), -1);                                 // 뜻 모르는 보기는 안 누른다

// 여는 시각 전의 다음 단추 (2026-11-22 실제 화면의 글자)
assert.equal(R.openTime("26. 11. 23.(월) 09:00 예약오픈"), new Date(2026, 10, 23, 9, 0).getTime());
assert.equal(R.openTime("다음단계"), null);

console.log("rules ok");
