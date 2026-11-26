// 자동화_목록.md 를 만든다 — 우리가 가진 자동화, 무엇이 깨우는지, 무엇을 받아 무엇을 내놓는지, 서로 어떻게 이어지는지.
// 새 자동화를 만들거나 고치기 전에 그 문서부터 읽는다(CLAUDE.md). 손으로 쓰지 않고 설정에서 뽑으므로 낡지 않는다.
//
//   node scripts/automation-list.mjs      # 저장소 맨 위의 자동화_목록.md 를 다시 쓴다
//
// 자료: app/workspaces/<사무실>.ts(자동화·직원·받는 것·내놓는 것) · worker/schedule.ts(실제 예약표) · automations/ 폴더.
// 문서가 설정과 어긋나면 tests/automation-list.test.mjs 가 잡는다. 날짜·시각은 넣지 않는다(돌릴 때마다 같아야 한다).
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
// Node 의 타입 제거 실행은 확장자 없는 상대 import 를 못 읽으므로 .ts 를 직접 적는다
import { WAKE_LABEL, wakeNote, wakeOf } from "../app/flow-rules.ts";
import { workspace as assembly } from "../app/workspaces/assembly.ts";
import { workspace as home } from "../app/workspaces/home.ts";
import { workspace as side } from "../app/workspaces/side.ts";
import { SCHEDULES } from "../worker/schedule.ts";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const OUT_FILE = "자동화_목록.md";
const WORKSPACES = [assembly, home, side];
const isReal = (a) => Boolean(a.workflow || a.local);
const dirExists = (name) => Boolean(name) && fs.existsSync(path.join(ROOT, "automations", name));

/** 코드 폴더 이름 — 설정에 적었으면 그것, 아니면 워크플로 이름, 아니면 id */
function codeDir(a) {
  const byWorkflow = a.workflow?.replace(/\.yml$/, "");
  return [a.code, byWorkflow, a.id].find(dirExists) ?? null;
}

/** README 첫 제목 줄 — 사이트에 붙지 않은 폴더가 무엇인지 한 줄로 */
function readmeTitle(dir) {
  try {
    const first = fs.readFileSync(path.join(ROOT, "automations", dir, "README.md"), "utf-8").split(/\r?\n/).find((l) => l.startsWith("# "));
    return first ? first.slice(2).trim() : "";
  } catch {
    return "";
  }
}

/** 그 워크플로의 실제 예약(예약표) */
const jobsOf = (a) => (a.workflow ? SCHEDULES.filter((j) => j.workflow === a.workflow) : []);

/** "정해진 시각에 — 매일 09:00". 설정에 예약 문구를 비워 둔 자동화(주말 일정 — '예약 놓침' 경고 때문)도 예약표에 있으면 예약으로 적는다 */
function whenText(a) {
  const kind = wakeOf(a);
  if (kind === "manual" && jobsOf(a).length) return `${WAKE_LABEL.schedule} — ${jobsOf(a).map((j) => j.note).join(" · ")}`;
  return [WAKE_LABEL[kind], wakeNote(a)].filter(Boolean).join(" — ");
}

/** 사람에게 가서 끝나는 것 — 다른 자동화가 받아 쓸 자리가 아니다 */
const forPeople = (r) => r.startsWith("텔레그램") || r === "인스타그램" || r === "아이사랑 예약";

export function render() {
  const all = WORKSPACES.flatMap((w) => w.automations.filter(isReal).map((a) => ({ w, a })));
  const label = ({ w, a }) => `${a.name}(\`${a.id}\`, ${w.label})`;
  const makers = (r) => all.filter(({ a }) => a.gives?.includes(r));
  const users = (r) => all.filter(({ a }) => a.takes?.includes(r));
  const cell = (xs) => (xs?.length ? xs.join("<br>") : "–");
  const L = [];

  L.push("# 자동화 목록", "");
  L.push("> **손으로 고치지 않는다.** `node scripts/automation-list.mjs` 가 사무실 설정(`app/workspaces/*.ts`)과 예약표(`worker/schedule.ts`)에서 만든다.");
  L.push("> 자동화를 더하거나 고쳤으면 다시 돌린다 — 어긋나면 `tests/automation-list.test.mjs` 가 실패한다.");
  L.push(">");
  L.push("> **새 자동화를 만들거나 있는 것을 고치기 전에 이 문서부터 읽는다.** 이미 있는 자동화가 내놓는 것을 받아 쓸 수 있는지,");
  L.push("> 같은 일을 하는 자동화가 이미 있는지 먼저 본다.", "");

  L.push(`## 한눈에 — 실제로 도는 자동화 ${all.length}개`, "");
  L.push("| 사무실 | 자동화 | 깨어나는 때 | 받는 것 | 내놓는 것 | 코드 |", "|---|---|---|---|---|---|");
  for (const { w, a } of all) {
    const dir = codeDir(a);
    L.push(`| ${w.label} | **${a.name}** \`${a.id}\` | ${whenText(a)} | ${cell(a.takes)} | ${cell(a.gives)} | ${dir ? `\`automations/${dir}/\`` : "–"} |`);
  }
  L.push("");

  // 한 자동화가 내놓은 것을 다른 자동화가 받는 자리 = 지금 이어져 있는 곳. 받는 곳이 없는 것 = 새 자동화가 붙을 수 있는 곳
  const produced = [...new Set(all.flatMap(({ a }) => a.gives ?? []))].filter((r) => !forPeople(r));
  L.push("## 이어져 있는 것", "");
  L.push("한 자동화가 내놓은 것을 다른 자동화가 받으면 이어진 것이다. **받는 자동화가 없는 줄은 새 자동화를 붙일 수 있는 자리**다. 사람에게 가서 끝나는 것(텔레그램·인스타그램)은 뺐다.", "");
  L.push("| 내놓는 것 | 만드는 자동화 | 받아 쓰는 자동화 |", "|---|---|---|");
  for (const r of produced) {
    const to = users(r);
    L.push(`| ${r} | ${makers(r).map(label).join("<br>")} | ${to.length ? to.map(label).join("<br>") : "– (아직 없음)"} |`);
  }
  L.push("");
  const shared = [...new Set(all.flatMap(({ a }) => a.takes ?? []))].filter((r) => !produced.includes(r) && users(r).length > 1);
  if (shared.length) {
    L.push("같은 것을 함께 받아 쓰는 자동화(만드는 쪽은 바깥):", "");
    for (const r of shared) L.push(`- ${r} ← ${users(r).map(label).join(", ")}`);
    L.push("");
  }

  for (const w of WORKSPACES) {
    const real = w.automations.filter(isReal);
    L.push(`## ${w.label} 사무실 (\`/${w.id}\`)`, "");
    if (!real.length) L.push("실제로 도는 자동화가 아직 없다.", "");
    for (const a of real) {
      const dept = w.departments.find((d) => d.id === a.dept);
      const dir = codeDir(a);
      const jobs = jobsOf(a);
      const next = (a.gives ?? []).flatMap((r) => users(r).filter((x) => x.a !== a).map((x) => `${label(x)} ← ${r}`));
      const prev = (a.takes ?? []).flatMap((r) => makers(r).filter((x) => x.a !== a).map((x) => `${label(x)} → ${r}`));
      L.push(`### ${a.name} (\`${a.id}\`)`, "");
      L.push(`- 팀: ${dept?.name ?? a.dept}`);
      L.push(`- 깨어나는 때: ${whenText(a)}`);
      for (const j of jobs) L.push(`  - 예약표: \`${j.cron}\`(UTC) — ${j.note}`);
      L.push(`- 받는 것: ${a.takes?.join(", ") ?? "–"}`);
      L.push(`- 내놓는 것: ${a.gives?.join(", ") ?? "–"}`);
      if (prev.length) L.push(`- 앞에서 받음: ${prev.join(" / ")}`);
      if (next.length) L.push(`- 뒤로 이어짐: ${next.join(" / ")}`);
      L.push("- 직원(일하는 순서):");
      a.tasks.forEach((t, i) => L.push(`  ${i + 1}. **${t.title ?? t.name}** — ${t.name}: ${t.role}${t.planned ? " _(준비 중)_" : ""}`));
      const where = [dir ? `\`automations/${dir}/\`` : null, a.workflow ? `\`.github/workflows/${a.workflow}\`` : "이 PC 에서 돈다(워크플로 없음)"].filter(Boolean);
      L.push(`- 코드: ${where.join(" · ")}`, "");
    }
    const planned = w.automations.filter((a) => !isReal(a));
    if (planned.length) {
      L.push(`이름만 있고 코드가 없는 것(${planned.length}개) — 만들 때 이 자리를 쓴다:`, "");
      for (const a of planned) L.push(`- ${a.name} (\`${a.id}\`) — ${a.tasks.map((t) => t.role).join(" / ")}`);
      L.push("");
    }
  }

  const used = new Set(all.map(({ a }) => codeDir(a)).filter(Boolean));
  const loose = fs.readdirSync(path.join(ROOT, "automations"), { withFileTypes: true })
    .filter((d) => d.isDirectory() && !d.name.startsWith("_") && !d.name.startsWith(".") && !used.has(d.name))
    .map((d) => d.name).sort();
  L.push("## 사이트에 붙지 않은 코드 폴더", "");
  L.push("`automations/` 아래에 있지만 사무실 설정의 자동화와 이어지지 않은 폴더. 공용 모듈이거나, 이 PC 에서만 쓰거나, 아직 사이트에 올리지 않은 것이다.", "");
  for (const d of loose) L.push(`- \`automations/${d}/\`${readmeTitle(d) ? ` — ${readmeTitle(d)}` : ""}`);
  L.push("");
  return L.join("\n");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  fs.writeFileSync(path.join(ROOT, OUT_FILE), render(), "utf-8");
  console.log(`${OUT_FILE} 을(를) 다시 썼습니다`);
}
