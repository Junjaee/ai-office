import { test } from "node:test";
import assert from "node:assert/strict";
import { deriveDeptStatus, summarize, STALE_HOURS } from "../app/status-rules.ts";

const now = new Date("2026-09-09T15:00:00+09:00");
const base = { id: "minutes", name: "국회회의록 수집", dept: "research", ok: true, running: false,
  updated_at: "2026-09-09T13:38:12+09:00", summary: "신규 0건", counts: { new: 0, replaced: 0, failed: 0, total: 5894 },
  next_run: "매일 09:00", log: [], link: "" };

test("정상이고 최근이면 완료", () => {
  assert.equal(deriveDeptStatus(base, now), "완료");
});

test("실행 중이면 진행 중", () => {
  assert.equal(deriveDeptStatus({ ...base, running: true }, now), "진행 중");
});

test("실패면 오류", () => {
  assert.equal(deriveDeptStatus({ ...base, ok: false }, now), "오류");
});

test("STALE_HOURS 넘게 갱신이 없으면 대기", () => {
  const old = new Date(now.getTime() - (STALE_HOURS + 1) * 3600 * 1000).toISOString();
  assert.equal(deriveDeptStatus({ ...base, updated_at: old }, now), "대기");
});

test("summarize: ops·secretary 집계", () => {
  const all = [base, { ...base, id: "news", dept: "brand", ok: false }];
  const s = summarize(all, now);
  assert.equal(s.total, 2);
  assert.equal(s.ok, 1);
  assert.equal(s.error, 1);
  assert.equal(s.opsStatus, "오류");
  assert.match(s.brief, /2개 팀.*1개 정상.*1개 오류/);
});

test("summarize: 실제 팀이 없으면 대기", () => {
  const s = summarize([], now);
  assert.equal(s.opsStatus, "대기");
  assert.match(s.brief, /연결된 자동화 없음/);
});
