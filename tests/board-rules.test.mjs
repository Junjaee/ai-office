import { test } from "node:test";
import assert from "node:assert/strict";
// Node 의 타입 제거 실행은 확장자 없는 상대 import 를 못 읽으므로 규칙·사무실 파일을 직접 읽는다
import { BOARD_ORDER, boardGroups, pickOnBoard, staffName } from "../app/board-rules.ts";
import { workspace as assembly } from "../app/workspaces/assembly.ts";
import { workspace as home } from "../app/workspaces/home.ts";
import { workspace as side } from "../app/workspaces/side.ts";

const WORKSPACE_LIST = [assembly, home, side];
const view = (id, state) => ({ id, dept: "qa", name: id, phase: state, state, sub: "", tasks: {} });

test("직원 이름은 직업 이름, 없으면 업무명", () => {
  assert.equal(staffName({ name: "자막 수신", title: "속기사" }), "속기사");
  assert.equal(staffName({ name: "자막 수신" }), "자막 수신");
});

test("업무 목록은 일하는 중 → 오류 → 끝남 → 쉬는 중 → 준비 중 순서, 빈 묶음은 없다", () => {
  const groups = boardGroups([view("a", "done"), view("b", "idle"), view("c", "running"), view("d", "error"), view("e", "done")]);
  assert.deepEqual(
    groups.map((g) => g.state),
    ["running", "error", "done", "idle"],
  );
  assert.deepEqual(
    groups[2].items.map((v) => v.id),
    ["a", "e"],
  ); // 묶음 안은 받은 순서 그대로
  assert.equal(boardGroups([]).length, 0);
  assert.equal(BOARD_ORDER.length, 5);
});

test("펼쳐 보일 업무: 고른 것이 있으면 그것, 없으면 맨 위", () => {
  const groups = boardGroups([view("a", "done"), view("c", "running")]);
  assert.equal(pickOnBoard(groups, null), "c"); // 처음 열면 일하는 중인 업무
  assert.equal(pickOnBoard(groups, "a"), "a");
  assert.equal(pickOnBoard(groups, "없는것"), "c"); // 팀을 바꿔 목록에서 사라졌으면 맨 위로
  assert.equal(pickOnBoard([], "a"), null);
});

test("실제로 도는 자동화의 직원은 모두 직업 이름이 있고, 사무실 안에서 겹치지 않는다", () => {
  for (const ws of WORKSPACE_LIST) {
    const titles = [];
    for (const a of ws.automations) {
      if (!a.workflow && !a.local) continue;
      for (const t of a.tasks) {
        assert.ok(t.title, `${ws.id}/${a.id}/${t.id}: 직업 이름(title)이 없다 — 새 직원에게도 직업 이름을 지어 준다`);
        titles.push(t.title);
      }
    }
    assert.equal(new Set(titles).size, titles.length, `${ws.id}: 같은 직업 이름을 가진 직원이 둘 있다`);
  }
});
