import { test } from "node:test";
import assert from "node:assert/strict";
import { placeFor, poseFor, needsWalk, toOfficeInput, agentId } from "../app/game/office-model.ts";

test("placeFor: 쉬는 중은 라운지, 오류는 책상 옆, 나머지는 책상", () => {
  assert.equal(placeFor("idle"), "lounge");
  assert.equal(placeFor("error"), "deskSide");
  for (const s of ["running", "done", "planned"]) assert.equal(placeFor(s), "desk");
});

test("poseFor: 일하는 중은 타이핑, 끝남은 앉기, 오류는 서기", () => {
  assert.deepEqual(poseFor("running"), { anim: "type", facing: "up" });
  assert.deepEqual(poseFor("done"), { anim: "sit", facing: "up" });
  assert.deepEqual(poseFor("error"), { anim: "idle", facing: "down" });
  assert.equal(poseFor("idle").anim, "sit");
});

test("needsWalk: 라운지↔책상만 걷는다", () => {
  assert.equal(needsWalk("idle", "running"), true);
  assert.equal(needsWalk("done", "idle"), true);
  assert.equal(needsWalk("error", "idle"), true);
  assert.equal(needsWalk("running", "done"), false);
  assert.equal(needsWalk("done", "error"), false);
  assert.equal(needsWalk("running", "running"), false);
});

const DEFS = [
  { id: "minutes", dept: "research", name: "회의록", workflow: "minutes.yml",
    tasks: [{ id: "collect", name: "회의록 수집", role: "" }, { id: "replace", name: "확정본 교체", role: "" }, { id: "audit", name: "국감", role: "", planned: true }] },
  { id: "news", dept: "brand", name: "기사", tasks: [{ id: "collect", name: "기사 수집", role: "" }] },
];

test("toOfficeInput: 직원 id 와 상태, hotRoom", () => {
  const views = [
    { id: "minutes", dept: "research", name: "회의록", phase: "running", state: "running", sub: "",
      tasks: { collect: { state: "running", note: "" }, replace: { state: "running", note: "" }, audit: { state: "planned", note: "" } } },
    { id: "news", dept: "brand", name: "기사", phase: "planned", state: "planned", sub: "", tasks: {} },
  ];
  const input = toOfficeInput(views, DEFS);
  assert.equal(input.agents[agentId("minutes", "collect")], "running");
  assert.equal(input.agents["minutes.audit"], "planned");
  assert.equal(input.agents["news.collect"], "planned");   // view.tasks 에 없으면 자동화 상태 상속
  assert.equal(input.hotRoom, "research");
});

test("toOfficeInput: view 가 없으면 쉬는 중, planned 작업은 항상 준비 중", () => {
  const input = toOfficeInput([], DEFS);
  assert.equal(input.agents["minutes.collect"], "idle");
  assert.equal(input.agents["minutes.audit"], "planned");
  assert.equal(input.hotRoom, null);
});
