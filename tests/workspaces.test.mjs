import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
// Node 의 타입 제거 실행은 확장자 없는 상대 import 를 못 읽으므로 사무실 파일을 직접 읽는다
import { workspace as assembly } from "../app/workspaces/assembly.ts";
import { workspace as home } from "../app/workspaces/home.ts";

const WORKSPACE_LIST = [assembly, home];
const DEFAULT_WORKSPACE = "assembly";
const isWorkspaceId = (id) => WORKSPACE_LIST.some((w) => w.id === id);
const ROOT = path.resolve(import.meta.dirname, "..");

const ENGINE_IDS = ["research", "brand", "strategy1", "qa", "strategy2", "reels", "carousel", "partner", "finance", "review", "ops", "secretary"];
const MAX_SEATS = 6;

/** config.actions.yaml 의 `tasks: [a, b]` 한 줄만 읽는다 (yaml 의존성 없이) */
function yamlTaskIds(file) {
  const text = fs.readFileSync(file, "utf-8");
  const m = text.match(/^tasks:\s*\[([^\]]*)\]/m);
  if (!m) return null;
  return m[1].split(",").map((s) => s.trim()).filter(Boolean).sort();
}

test("기본 사무실이 목록에 있다", () => {
  assert.ok(isWorkspaceId(DEFAULT_WORKSPACE));
  assert.ok(WORKSPACE_LIST.length >= 2);
});

for (const ws of WORKSPACE_LIST) {
  test(`${ws.id}: 엔진이 요구하는 부서 12개 id 그대로`, () => {
    assert.deepEqual(ws.departments.map((d) => d.id), ENGINE_IDS);
  });
  test(`${ws.id}: 숨김 부서 id가 실제 부서 id`, () => {
    for (const id of ws.hidden) assert.ok(ENGINE_IDS.includes(id), id);
  });
  test(`${ws.id}: 자동화 id 중복 없음, 부서 id 유효`, () => {
    const ids = ws.automations.map((a) => a.id);
    assert.equal(new Set(ids).size, ids.length);
    for (const a of ws.automations) assert.ok(ENGINE_IDS.includes(a.dept), `${a.id} dept ${a.dept}`);
  });
  test(`${ws.id}: 자동화마다 하위 작업 1개 이상, 직원 이름 유일`, () => {
    const names = [];
    for (const a of ws.automations) {
      assert.ok(a.tasks.length >= 1, a.id);
      for (const t of a.tasks) names.push(t.name);
    }
    assert.equal(new Set(names).size, names.length, "직원 이름 중복");
  });
  test(`${ws.id}: 부서별 하위 작업 합계 ≤ ${MAX_SEATS}석`, () => {
    const perDept = {};
    for (const a of ws.automations) perDept[a.dept] = (perDept[a.dept] ?? 0) + a.tasks.length;
    for (const [dept, n] of Object.entries(perDept)) assert.ok(n <= MAX_SEATS, `${dept} ${n}석`);
  });
  test(`${ws.id}: workflow 가 있으면 파일이 존재하고 planned 아닌 작업이 1개 이상`, () => {
    for (const a of ws.automations.filter((x) => x.workflow)) {
      assert.ok(fs.existsSync(path.join(ROOT, ".github/workflows", a.workflow)), `${a.id}: ${a.workflow} 없음`);
      assert.ok(a.tasks.some((t) => !t.planned), `${a.id}: 실제 작업 없음`);
    }
  });
  test(`${ws.id}: workflow 자동화의 Python 설정 tasks 와 사무실 설정 tasks 일치`, () => {
    for (const a of ws.automations.filter((x) => x.workflow)) {
      const file = path.join(ROOT, "automations", a.id, "config.actions.yaml");
      assert.ok(fs.existsSync(file), `${file} 없음`);
      const yamlIds = yamlTaskIds(file);
      assert.ok(yamlIds, `${file} 에 tasks: [..] 절이 없음`);
      const cfgIds = a.tasks.filter((t) => !t.planned).map((t) => t.id).sort();
      assert.deepEqual(yamlIds, cfgIds, `${a.id}: yaml ${yamlIds} vs 설정 ${cfgIds}`);
    }
  });
}
