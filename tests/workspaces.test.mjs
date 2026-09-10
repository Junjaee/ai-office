import { test } from "node:test";
import assert from "node:assert/strict";
// Node 의 타입 제거 실행은 확장자 없는 상대 import 를 못 읽으므로 사무실 파일을 직접 읽는다
import { workspace as assembly } from "../app/workspaces/assembly.ts";
import { workspace as home } from "../app/workspaces/home.ts";

const WORKSPACE_LIST = [assembly, home];
const DEFAULT_WORKSPACE = "assembly";
const isWorkspaceId = (id) => WORKSPACE_LIST.some((w) => w.id === id);

const ENGINE_IDS = ["research", "brand", "strategy1", "qa", "strategy2", "reels", "carousel", "partner", "finance", "review", "ops", "secretary"];

test("기본 사무실이 목록에 있다", () => {
  assert.ok(isWorkspaceId(DEFAULT_WORKSPACE));
  assert.ok(WORKSPACE_LIST.length >= 2);
});

for (const ws of WORKSPACE_LIST) {
  test(`${ws.id}: 엔진이 요구하는 부서 12개 id 그대로`, () => {
    assert.deepEqual(ws.departments.map((d) => d.id), ENGINE_IDS);
  });
  test(`${ws.id}: 부서마다 팀장 정확히 1명`, () => {
    for (const id of ENGINE_IDS) {
      const leads = ws.staff.filter((s) => s.dept === id && s.rank === "lead");
      assert.equal(leads.length, 1, `${id} 팀장 수 ${leads.length}`);
    }
  });
  test(`${ws.id}: 숨김·준비중 부서 id가 실제 부서 id`, () => {
    for (const id of [...ws.hidden, ...Object.keys(ws.pending)]) assert.ok(ENGINE_IDS.includes(id), id);
  });
  test(`${ws.id}: 직원 이름 중복 없음`, () => {
    const names = ws.staff.map((s) => s.name);
    assert.equal(new Set(names).size, names.length);
  });
}
