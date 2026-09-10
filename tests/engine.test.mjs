import { test } from "node:test";
import assert from "node:assert/strict";
import { OfficeEngine } from "../app/game/engine.ts";
import { createWorld } from "../app/game/world.ts";
import { buildStaff } from "../app/game/staff.ts";

const DEPT = { id: "research", name: "수집팀", short: "lab", icon: "📜" };
const AUTOS = [
  { id: "minutes", dept: "research", name: "회의록", workflow: "minutes.yml", tasks: [
    { id: "collect", name: "수집", role: "" }, { id: "replace", name: "교체", role: "" }, { id: "audit", name: "국감", role: "", planned: true },
  ] },
];

function make() {
  const world = createWorld([DEPT]);
  return { world, engine: new OfficeEngine(buildStaff(AUTOS), world) };
}

/** 점이 라운지 방 안에 있는가 */
function inLounge(world, p) {
  const L = world.lounge;
  return p.x > L.x && p.x < L.x + L.w - 1 && p.y > L.y && p.y < L.y + L.h - 1;
}

test("createWorld: 부서 1개면 폭이 라운지 기준으로 줄고, 4개면 COLS", () => {
  assert.equal(createWorld([DEPT]).cols, 24);
  assert.equal(createWorld([1, 2, 3, 4].map((i) => ({ ...DEPT, id: `d${i}` }))).cols, 73);
});

test("place: 쉬는 중은 라운지 소파, 끝남은 책상, 준비 중은 책상", () => {
  const { engine, world } = make();
  engine.place({ agents: { "minutes.collect": "idle", "minutes.replace": "done", "minutes.audit": "planned" }, hotRoom: null });
  const [a, b, c] = engine.agents;
  assert.equal(inLounge(world, a), true);
  assert.equal(a.anim, "sit");
  assert.deepEqual({ x: b.x, y: b.y }, b.seat);
  assert.equal(b.anim, "sit");
  assert.equal(c.state, "planned");
  assert.equal(engine.tick(0.05), false, "아무도 걷지 않는다");
});

test("apply: 쉬는 중→일하는 중이면 라운지에서 책상까지 걸어가고, 도착하면 타이핑", () => {
  const { engine } = make();
  engine.place({ agents: { "minutes.collect": "idle", "minutes.replace": "idle" }, hotRoom: null });
  const a = engine.agents[0];
  const changed = engine.apply({ agents: { "minutes.collect": "running", "minutes.replace": "idle" }, hotRoom: "research" });
  assert.equal(changed, true);
  assert.ok(a.path.length > 0, "경로가 있어야 한다");
  assert.equal(a.anim, "walk");
  let steps = 0;
  while (engine.tick(0.05) && steps < 2000) steps += 1;
  assert.ok(steps < 2000, "도착해야 한다");
  assert.deepEqual({ x: a.x, y: a.y }, a.seat);
  assert.equal(a.anim, "type");
  assert.equal(engine.hotRoom(), "research");
});

test("apply: 일하는 중→오류는 걷지 않고 책상 옆에 선다, 같은 상태는 변화 없음", () => {
  const { engine } = make();
  engine.place({ agents: { "minutes.collect": "running", "minutes.replace": "running" }, hotRoom: "research" });
  const a = engine.agents[0];
  engine.apply({ agents: { "minutes.collect": "error", "minutes.replace": "done" }, hotRoom: null });
  assert.equal(a.path.length, 0);
  assert.deepEqual({ x: a.x, y: a.y }, a.side);
  assert.equal(a.anim, "idle");
  assert.equal(engine.apply({ agents: { "minutes.collect": "error", "minutes.replace": "done" }, hotRoom: null }), false);
});

test("apply: 끝남→쉬는 중이면 책상에서 라운지로 걸어간다", () => {
  const { engine, world } = make();
  engine.place({ agents: { "minutes.collect": "done", "minutes.replace": "done" }, hotRoom: null });
  const a = engine.agents[0];
  engine.apply({ agents: { "minutes.collect": "idle", "minutes.replace": "done" }, hotRoom: null });
  assert.ok(a.path.length > 0);
  let steps = 0;
  while (engine.tick(0.05) && steps < 2000) steps += 1;
  assert.equal(inLounge(world, a), true);
  assert.equal(a.anim, "sit");
});
