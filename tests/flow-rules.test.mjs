import { test } from "node:test";
import assert from "node:assert/strict";
// Node 의 타입 제거 실행은 확장자 없는 상대 import 를 못 읽으므로 규칙·사무실 파일을 직접 읽는다
import { WAKE_LABEL, WAKE_NOTE, WAKE_ORDER, wakeGroups, wakeNote, wakeOf } from "../app/flow-rules.ts";
import { workspace as assembly } from "../app/workspaces/assembly.ts";
import { workspace as home } from "../app/workspaces/home.ts";
import { workspace as side } from "../app/workspaces/side.ts";

const WORKSPACE_LIST = [assembly, home, side];
const isReal = (a) => Boolean(a.workflow || a.local);

test("깨우는 방식 네 가지를 가린다", () => {
  assert.equal(wakeOf({ id: "a", dept: "x", name: "a", local: true, schedule: "평일 (이 PC)", tasks: [] }), "local");
  assert.equal(wakeOf({ id: "b", dept: "x", name: "b", workflow: "b.yml", wake: "새 메일이 오면", tasks: [] }), "event");
  assert.equal(wakeOf({ id: "c", dept: "x", name: "c", workflow: "c.yml", schedule: "매일 09:00", tasks: [] }), "schedule");
  assert.equal(wakeOf({ id: "d", dept: "x", name: "d", workflow: "d.yml", tasks: [] }), "manual");
});

test("예약과 사건에 둘 다 걸리면 사건으로 본다 (가계부)", () => {
  const ledger = { id: "ledger", dept: "x", name: "지출·정산", workflow: "ledger.yml", schedule: "6시간마다", wake: "새 카드 문자가 오면", tasks: [] };
  assert.equal(wakeOf(ledger), "event");
  assert.equal(wakeNote(ledger), "새 카드 문자가 오면 · 6시간마다에도"); // 예약도 문구에 남는다
});

test("자동화 이름 옆 한 줄", () => {
  assert.equal(wakeNote({ id: "a", dept: "x", name: "a", workflow: "a.yml", schedule: "3시간마다", tasks: [] }), "3시간마다");
  assert.equal(wakeNote({ id: "b", dept: "x", name: "b", workflow: "b.yml", wake: "새 메일이 오면", tasks: [] }), "새 메일이 오면");
  assert.equal(wakeNote({ id: "c", dept: "x", name: "c", workflow: "c.yml", tasks: [] }), "사이트에서 시작");
  assert.equal(wakeNote({ id: "d", dept: "x", name: "d", local: true, tasks: [] }), ""); // 적을 것이 없으면 빈 칸
});

test("묶음은 정해진 순서로 나오고 빈 묶음은 빠진다", () => {
  const groups = wakeGroups([
    { id: "a", dept: "x", name: "a", workflow: "a.yml", tasks: [] }, // manual
    { id: "b", dept: "x", name: "b", workflow: "b.yml", wake: "일이 생기면", tasks: [] }, // event
  ]);
  assert.deepEqual(
    groups.map((g) => g.kind),
    ["event", "manual"],
  );
  assert.equal(wakeGroups([]).length, 0);
});

test("실제로 도는 자동화가 묶음에서 하나도 빠지지 않는다", () => {
  for (const ws of WORKSPACE_LIST) {
    const real = ws.automations.filter(isReal);
    const grouped = wakeGroups(real).flatMap((g) => g.items.map((a) => a.id));
    assert.deepEqual(
      [...grouped].sort(),
      real.map((a) => a.id).sort(),
      `${ws.id}: 묶음에서 빠진 자동화가 있다`,
    );
    assert.equal(new Set(grouped).size, grouped.length, `${ws.id}: 한 자동화가 두 묶음에 들어갔다`);
  }
});

test("묶음마다 이름과 설명이 있다", () => {
  for (const kind of WAKE_ORDER) {
    assert.ok(WAKE_LABEL[kind]?.length > 0, `${kind}: 이름 없음`);
    assert.ok(WAKE_NOTE[kind]?.length > 0, `${kind}: 설명 없음`);
  }
});

test("wake 를 적은 자동화는 깨우는 쪽 코드가 있다", () => {
  // 사건으로 깨어나려면 Worker 가 그 자동화를 깨워야 한다(worker/schedule.ts 의 MAIL_JOB·gmail.ts·webcast.ts).
  // 설정에만 wake 를 적고 깨우는 코드가 없으면 영원히 안 도는 자동화가 된다.
  const wakers = ["mail", "ledger", "speech", "sort"];
  for (const ws of WORKSPACE_LIST) {
    for (const a of ws.automations) {
      if (a.wake) assert.ok(wakers.includes(a.id), `${ws.id}/${a.id}: wake 를 적었는데 깨우는 쪽이 없다`);
    }
  }
});
