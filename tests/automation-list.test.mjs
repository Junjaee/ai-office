import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { OUT_FILE, render } from "../scripts/automation-list.mjs";
import { workspace as assembly } from "../app/workspaces/assembly.ts";
import { workspace as home } from "../app/workspaces/home.ts";
import { workspace as side } from "../app/workspaces/side.ts";

const ROOT = path.resolve(import.meta.dirname, "..");
const WORKSPACE_LIST = [assembly, home, side];
const lf = (s) => s.replace(/\r\n/g, "\n"); // git 이 줄바꿈을 바꿔 내려받아도 같게 본다

test("자동화_목록.md 가 설정과 같다 — 다르면 node scripts/automation-list.mjs 를 다시 돌린다", () => {
  const saved = fs.readFileSync(path.join(ROOT, OUT_FILE), "utf-8");
  assert.equal(lf(saved), lf(render()), "자동화를 더하거나 고친 뒤 목록을 다시 만들지 않았다: node scripts/automation-list.mjs");
});

test("실제로 도는 자동화는 받는 것·내놓는 것을 적는다", () => {
  // 적지 않으면 목록의 '이어져 있는 것' 표에서 빠져, 다음에 자동화를 만들 때 연계할 자리를 못 본다
  for (const ws of WORKSPACE_LIST) {
    for (const a of ws.automations) {
      if (!a.workflow && !a.local) continue;
      assert.ok(a.takes?.length, `${ws.id}/${a.id}: takes(받는 것)가 없다`);
      assert.ok(a.gives?.length, `${ws.id}/${a.id}: gives(내놓는 것)가 없다`);
    }
  }
});

test("목록에 실제로 도는 자동화가 빠짐없이 나온다", () => {
  const text = render();
  for (const ws of WORKSPACE_LIST) {
    for (const a of ws.automations) {
      if (a.workflow || a.local) assert.ok(text.includes(`(\`${a.id}\`)`), `${ws.id}/${a.id} 가 목록에 없다`);
    }
  }
  assert.ok(!/\d{4}-\d{2}-\d{2}T\d{2}:/.test(text), "만든 시각을 넣지 않는다 — 돌릴 때마다 같아야 한다");
});
